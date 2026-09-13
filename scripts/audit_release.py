"""Audit only intended distributable sources and artifacts."""

from pathlib import Path
from zipfile import ZipFile
import json, re, hashlib

ROOT = Path(__file__).resolve().parents[1]
forbidden = [
    r"/Users/",
    r"/private/",
    r"(?i)black_path",
    r"(?i)anime80s",
    r"(?i)open_clip",
    r"(?i)clip_eval",
    r"(?i)api[_-]?key\s*=",
    r"ghp_[A-Za-z0-9]{20,}",
    r"sk-proj-",
]
files = []
for pattern in (
    "blender_watercolor/**/*.py",
    "blender_watercolor/*.toml",
    "tests/*.py",
    "scripts/*.py",
    "docs/*.md",
    "examples/*.md",
    "*.md",
    "*.toml",
    ".github/workflows/*.yml",
):
    files.extend(ROOT.glob(pattern))
problems = []
for p in files:
    content = p.read_text()
    if p.name == "audit_release.py":
        continue
    for regex in forbidden:
        if re.search(regex, content):
            problems.append((str(p.relative_to(ROOT)), regex))
archive = ROOT / "dist/blender_watercolor-0.1.0.zip"
with ZipFile(archive) as z:
    for name in z.namelist():
        if not (name.endswith((".py", ".toml")) or name == "LICENSE"):
            problems.append((name, "unexpected archive member"))
        if name.startswith("/") or ".." in Path(name).parts:
            problems.append((name, "unsafe archive path"))
    for required in (
        "__init__.py",
        "addon.py",
        "core/surface.py",
        "blender_manifest.toml",
        "LICENSE",
    ):
        if required not in z.namelist():
            problems.append((required, "missing"))
report = {
    "source_files": len(set(files)),
    "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "problems": problems,
}
(ROOT / "build/release-audit.json").write_text(json.dumps(report, indent=2))
assert not problems, problems
print(json.dumps(report, indent=2))
