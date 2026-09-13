"""Render an original, reproducible drying sequence for the release."""

import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy, numpy as np
import blender_watercolor
from blender_watercolor import addon
from blender_watercolor.core.surface import Paint, Settings

blender_watercolor.register()
bpy.ops.wm.open_mainfile(filepath=str(ROOT / "build/watercolor-demo.blend"))
scene = bpy.context.scene
scene.render.resolution_percentage = 70
scene.render.engine = "BLENDER_EEVEE"
out = ROOT / "build/drying"
out.mkdir(exist_ok=True)
sessions = []
records = []
for obj in bpy.data.objects:
    if "watercolor_id" not in obj:
        continue
    s = addon.get_session(obj)
    s.paint = Paint(s.paint.surface, Settings(gravity=0.15))
    s.history = []
    s.undo = []
    v = s.paint.surface.vertices
    triangles = s.paint.surface.triangles
    for k in range(3):
        target = np.array(obj.location) + np.array(
            [-0.5 + k * 0.45, -0.2 + k * 0.18, 0.2]
        )
        if "Sphere" in obj.name:
            target = np.array(obj.location) + np.array([-0.4 + k * 0.35, -0.5, 0.7])
        tri = int(np.argmin(np.linalg.norm(v[triangles].mean(1) - target, axis=1)))
        point = v[triangles[tri]].mean(0)
        ids, w = s.paint.surface.footprint(tri, point, 0.48)
        s.paint.apply(ids, w, pigment=k, water=0.15, load=1.0)
    sessions.append(s)
for frame in range(18):
    for s in sessions:
        if frame:
            for _ in range(120):
                s.paint.step()
        s.update()
    scene.render.filepath = str(out / f"wash{frame:03d}.png")
    bpy.ops.render.render(write_still=True)
    records.append({s.obj.name: s.paint.report() for s in sessions})
(out / "sequence.json").write_text(json.dumps(records, indent=2))
print("DRYING SEQUENCE COMPLETE")
