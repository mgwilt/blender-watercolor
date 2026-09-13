"""Check the generated release example for external dependencies."""

import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import bpy

bpy.ops.wm.open_mainfile(filepath=str(ROOT / "build/watercolor-demo.blend"))
assert not bpy.data.libraries
assert all(im.packed_file for im in bpy.data.images if im.source == "FILE" and im.users)
assert not [t for t in bpy.data.texts if not t.name.startswith("Watercolor State ")]
paths = list(bpy.utils.blend_paths(absolute=False, packed=False))
assert all("datafiles/assets/brushes/essentials_brushes-" in p for p in paths), paths
report = {
    "external_libraries": 0,
    "unpacked_used_file_images": 0,
    "text_blocks": "packed watercolor state only",
    "unused_builtin_brush_references": paths,
}
(ROOT / "build/delivery-audit.json").write_text(json.dumps(report, indent=2))
print(report)
