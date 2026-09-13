"""Measure first-stroke snapshot + sampling + Blender image feedback."""

import sys, time, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy, numpy as np
import blender_watercolor
from blender_watercolor import addon

blender_watercolor.register()
bpy.ops.wm.open_mainfile(filepath=str(ROOT / "build/watercolor-demo.blend"))
obj = bpy.data.objects["Curved Paper"]
s = addon.get_session(obj)
settings = bpy.context.scene.watercolor
settings.brush = "PIGMENT"
settings.pigment = "0"
settings.radius = 0.2
tri = len(s.paint.surface.triangles) // 2
point = s.paint.surface.vertices[s.paint.surface.triangles[tri]].mean(0)
samples = []
for _ in range(10):
    start = time.perf_counter()
    s.begin_stroke()
    s.dab(tri, point, settings, 0.1)
    s.update()
    samples.append((time.perf_counter() - start) * 1000)
report = dict(
    cells=len(s.paint.water),
    first_stroke_feedback_median_ms=float(np.median(samples)),
    first_stroke_feedback_max_ms=max(samples),
    includes=[
        "undo snapshot",
        "geodesic brush",
        "injection",
        "optics",
        "Blender image update",
    ],
    excludes=["OS event delivery", "viewport draw"],
)
(ROOT / "build/latency.json").write_text(json.dumps(report, indent=2))
print(report)
assert max(samples) < 100, "First-stroke feedback target missed"
