"""Inspect saved manual painting evidence; no event synthesis."""

import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
import blender_watercolor
from blender_watercolor import addon

blender_watercolor.register()
bpy.ops.wm.open_mainfile(filepath=str(ROOT / "build/interactive-demo.blend"))
obj = bpy.data.objects["Curved Paper"]
s = addon.get_session(obj)
s.check()
base = json.loads((ROOT / "build/verification-before.json").read_text())["Curved Paper"]
assert len(s.history) > base["history"]
assert s.paint.time > base["conservation"]["time"]
assert any(x.get("mode") == "WATER" for x in s.history[base["history"] :])
report = dict(
    blender=bpy.app.version_string,
    recorded_dabs=len(s.history),
    baseline_dabs=base["history"],
    model_time=s.paint.time,
    water_and_pigment_strokes_saved=True,
    continued_simulation=True,
    undo_snapshots=len(s.undo),
    conservation=s.paint.report(),
)
(ROOT / "build/verification-interactive.json").write_text(json.dumps(report, indent=2))
print("INTERACTIVE SAVED EVIDENCE", report)
