"""Build the installable ZIP from a strict source allowlist."""

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib, json

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "dist"
out.mkdir(exist_ok=True)
archive = out / "blender_watercolor-0.1.0.zip"
source = ROOT / "blender_watercolor"
files = sorted(
    p for p in source.rglob("*") if p.is_file() and p.suffix in {".py", ".toml"}
)
with ZipFile(archive, "w", ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, p.relative_to(source))
    z.write(ROOT / "LICENSE", "LICENSE")
(out / "checksums.json").write_text(
    json.dumps(
        {archive.name: hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2
    )
    + "\n"
)
print(archive)
