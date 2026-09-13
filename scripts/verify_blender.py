"""Run with Blender --background --factory-startup --python this_file.

Creates original test surfaces, verifies the actual extension, and saves a demo.
"""

import sys, time, json, hashlib, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
import numpy as np
from mathutils import Vector
import blender_watercolor
from blender_watercolor import addon

blender_watercolor.register()
OUT = ROOT / "build"
OUT.mkdir(exist_ok=True)
if "--reopen" in sys.argv:
    bpy.ops.wm.open_mainfile(filepath=str(OUT / "watercolor-demo.blend"))
    previous = json.loads((OUT / "verification-before.json").read_text())
    checked = []
    for obj in bpy.data.objects:
        if "watercolor_id" not in obj:
            continue
        s = addon.get_session(obj)
        s.check()
        before = previous[obj.name]
        digest = hashlib.sha256(
            s.paint.water.tobytes() + s.paint.mobile.tobytes() + s.paint.fixed.tobytes()
        ).hexdigest()
        assert digest == before["state_sha256"], obj.name
        assert len(s.history) == before["history"]
        assert len(s.undo) == before["undo"]
        pixels = np.array(s.image.pixels[:], np.float32)
        assert (
            hashlib.sha256(pixels.tobytes()).hexdigest() == before["pixels_sha256"]
        ), obj.name
        s.paint.step()
        s.update()
        assert s.image.packed_file
        checked.append(obj.name)
    (OUT / "verification-reopen.json").write_text(
        json.dumps(
            {
                "surfaces": checked,
                "state_exact": True,
                "pixels_exact": True,
                "resume": True,
                "blender": bpy.app.version_string,
            },
            indent=2,
        )
    )
    print("REOPEN PASS", checked)
    raise SystemExit

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
settings = bpy.context.scene.watercolor
settings.cells = 20000
settings.resolution = "1024"
settings.radius = 0.18
settings.gravity = 0.18


def patch(name, curved, location):
    n = 10
    vertices = []
    faces = []
    for j in range(n):
        for i in range(n):
            x = i / (n - 1) * 2 - 1
            y = j / (n - 1) * 2 - 1
            z = 0.35 * math.sin(x * 1.8) if curved else 0
            vertices.append((x, y, z))
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i
            faces.append((a, a + 1, a + n + 1, a + n))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    uv = mesh.uv_layers.new(name="Original UV")
    for p in mesh.polygons:
        for l in p.loop_indices:
            co = mesh.vertices[mesh.loops[l].vertex_index].co
            uv.data[l].uv = ((co.x + 1) / 2, (co.y + 1) / 2)
    return obj


objects = [
    patch("Flat Paper", False, (-2.4, 0, 0)),
    patch("Curved Paper", True, (0, 0, 0)),
]
bpy.ops.mesh.primitive_uv_sphere_add(
    segments=24, ring_count=12, radius=1, location=(2.5, 0, 0.5)
)
objects.append(bpy.context.object)
objects[-1].name = "Paper Sphere"
for poly in objects[-1].data.polygons:
    poly.use_smooth = True
report = {}
bench = {}
for obj in objects:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.context.view_layer.update()
    old = np.array([v.co[:] for v in obj.data.vertices])
    old_uv = [l.name for l in obj.data.uv_layers]
    start = time.perf_counter()
    s = addon.prepare(obj, settings)
    prep = time.perf_counter() - start
    np.testing.assert_array_equal(old, np.array([v.co[:] for v in obj.data.vertices]))
    for name in old_uv:
        assert name in obj.data.uv_layers
    assert len(np.unique(s.uvs.reshape(-1, 2), axis=0)) > len(obj.data.vertices)
    v = s.paint.surface.vertices
    zmax = v[:, 2].max()
    visible = (
        np.flatnonzero(v[:, 2] > zmax - 0.8)
        if "Sphere" in obj.name
        else np.arange(len(v))
    )
    start = time.perf_counter()
    dab_times = []
    for k in range(3):
        target = np.array(obj.location) + np.array(
            [-0.5 + k * 0.45, -0.2 + k * 0.18, 0.2]
        )
        if "Sphere" in obj.name:
            target = np.array(obj.location) + np.array([-0.4 + k * 0.35, -0.5, 0.7])
        tri = int(
            np.argmin(
                np.linalg.norm(v[s.paint.surface.triangles].mean(1) - target, axis=1)
            )
        )
        point = v[s.paint.surface.triangles[tri]].mean(0)
        settings.pigment = str(k)
        settings.radius = 0.48
        settings.load = 1.2
        settings.water = 0.35
        s.begin_stroke()
        t = time.perf_counter()
        s.dab(tri, point, settings)
        dab_times.append(time.perf_counter() - t)
        for _ in range(120):
            s.paint.step()
    # Actual controls: undo restores the complete prior stroke snapshot.
    saved = s.paint.dumps()
    s.begin_stroke()
    s.dab(tri, point, settings)
    s.undo_stroke()
    np.testing.assert_array_equal(addon.Paint.loads(saved).water, s.paint.water)
    settings.brush = "WATER"
    s.begin_stroke()
    s.dab(tri, point, settings, 0.3)
    settings.brush = "PIGMENT"
    s.update()
    s.store()
    s.paused = False
    tick = []
    for _ in range(15):
        t = time.perf_counter()
        s.tick()
        tick.append(time.perf_counter() - t)
    s.paused = True
    s.store()
    pixels = np.array(s.image.pixels[:], np.float32)
    report[obj.name] = dict(
        state_sha256=hashlib.sha256(
            s.paint.water.tobytes() + s.paint.mobile.tobytes() + s.paint.fixed.tobytes()
        ).hexdigest(),
        pixels_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
        history=len(s.history),
        undo=len(s.undo),
        conservation=s.paint.report(),
    )
    bench[obj.name] = dict(
        cells=len(v),
        triangles=len(s.paint.surface.triangles),
        prepare_seconds=prep,
        tick_median_ms=float(np.median(tick) * 1000),
        tick_max_ms=max(tick) * 1000,
        updates_per_second=1 / float(np.median(tick)),
        dab_max_ms=max(dab_times) * 1000,
    )
    assert max(abs(np.array(s.paint.report()["pigment_error"]))) < 1e-10
    assert abs(s.paint.report()["water_error"]) < 1e-10

# Original neutral studio scene; no inherited artwork or dependencies.
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1400
scene.render.resolution_y = 700
scene.render.resolution_percentage = 100
scene.world.color = (0.3, 0.3, 0.3)
scene.view_settings.view_transform = "Standard"
bpy.ops.object.light_add(type="AREA", location=(0, -1, 6))
bpy.context.object.data.energy = 250
bpy.context.object.data.shape = "DISK"
bpy.context.object.data.size = 7
bpy.ops.object.camera_add(location=(0, -5, 8))
camera = bpy.context.object
camera.rotation_euler = (
    (Vector((0, 0, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
)
camera.data.type = "ORTHO"
camera.data.ortho_scale = 8.5
scene.camera = camera
# Select the curved surface for immediate painting on reopen.
bpy.ops.object.select_all(action="DESELECT")
objects[1].select_set(True)
bpy.context.view_layer.objects.active = objects[1]
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.region_3d.view_distance = 8
            area.spaces.active.region_3d.view_location = (0, 0, 0)
            area.spaces.active.region_3d.view_rotation = (
                camera.rotation_euler.to_quaternion()
            )
            area.spaces.active.shading.type = "MATERIAL"
            area.spaces.active.show_region_ui = True
scene.render.filepath = str(OUT / "demo-eevee.png")
bpy.ops.render.render(write_still=True)
scene.render.filepath = "//demo-eevee.png"
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "watercolor-demo.blend"))
(OUT / "verification-before.json").write_text(json.dumps(report, indent=2))
(OUT / "benchmark.json").write_text(json.dumps(bench, indent=2))
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.render.resolution_percentage = 60
scene.render.filepath = str(OUT / "demo-cycles.png")
bpy.ops.render.render(write_still=True)
print("INTEGRATION PASS", json.dumps(bench))
