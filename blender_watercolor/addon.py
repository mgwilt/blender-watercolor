"""Native painting controls, bounded live simulation, and packed persistence."""

import base64
import hashlib
import io
import json
import time
import uuid
import zlib
import numpy as np
import bpy
import bmesh
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy_extras import view3d_utils
from bpy_extras.io_utils import ExportHelper
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from .core.surface import Surface, Paint, Settings
from .mesh import refine, make_uvs, Atlas

SESSIONS = {}
ACTIVE = None


def geometry_hash(obj):
    mesh = obj.data
    v = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", v)
    idx = np.empty(len(mesh.loops), np.int32)
    mesh.loops.foreach_get("vertex_index", idx)
    return hashlib.sha256(
        v.tobytes() + idx.tobytes() + np.asarray(obj.matrix_world).tobytes()
    ).hexdigest()


class Session:
    def __init__(self, obj, paint, uvs, size, image, signature):
        self.obj = obj
        self.paint = paint
        self.uvs = uvs
        self.size = size
        self.image = image
        self.signature = signature
        self.atlas = Atlas(paint.surface.triangles, uvs, size)
        self.bvh = BVHTree.FromPolygons(
            paint.surface.vertices.tolist(),
            paint.surface.triangles.tolist(),
            all_triangles=True,
        )
        self.undo = []
        self.history = []
        self.paused = True
        self.last_update = 0.0
        self.error = ""

    def check(self):
        if self.obj.mode != "OBJECT":
            raise ValueError("Return to Object Mode to paint")
        if geometry_hash(self.obj) != self.signature:
            raise ValueError(
                "Geometry or transform changed: restore it or Prepare Surface again"
            )

    def update(self):
        self.image.pixels.foreach_set(self.atlas.pixels_for(self.paint.colors()))
        self.image.update()
        self.last_update = time.perf_counter()

    def begin_stroke(self):
        self.undo.append((self.paint.dumps(compress=False), len(self.history)))
        self.undo = self.undo[-12:]

    def undo_stroke(self):
        if not self.undo:
            raise ValueError("No watercolor stroke to undo")
        data, length = self.undo.pop()
        self.paint = Paint.loads(data)
        self.history = self.history[:length]
        self.update()

    def dab(self, triangle, point, settings, strength=1.0):
        ids, weights = self.paint.surface.footprint(triangle, point, settings.radius)
        self.paint.apply(
            ids,
            weights,
            settings.brush,
            int(settings.pigment),
            settings.water * strength,
            settings.load * strength,
        )
        self.history.append(
            dict(
                time=self.paint.time,
                triangle=int(triangle),
                point=list(point),
                radius=settings.radius,
                mode=settings.brush,
                pigment=int(settings.pigment),
                water=settings.water * strength,
                load=settings.load * strength,
            )
        )

    def tick(self, budget=0.025):
        if self.paused:
            return
        start = time.perf_counter()
        steps = 0
        while time.perf_counter() - start < budget and steps < 8:
            self.paint.step()
            steps += 1
        self.update()

    def store(self):
        meta = dict(
            version=1,
            size=self.size,
            image=self.image.name,
            signature=self.signature,
            history=self.history,
            undo_codec="zlib",
        )
        output = io.BytesIO()
        np.savez_compressed(
            output,
            state=np.frombuffer(self.paint.dumps(), dtype=np.uint8),
            uvs=self.uvs,
            meta=json.dumps(meta),
            undo=np.array(
                [base64.b64encode(zlib.compress(d, 1)).decode() for d, _ in self.undo]
            ),
            undo_lengths=np.array([l for _, l in self.undo]),
        )
        name = "Watercolor State " + self.obj["watercolor_id"]
        block = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        block.clear()
        encoded = base64.b64encode(output.getvalue()).decode()
        block.write("\n".join(encoded[i : i + 76] for i in range(0, len(encoded), 76)))
        block.use_fake_user = True
        self.obj["watercolor_state"] = name
        self.image.pack()

    @classmethod
    def restore(cls, obj):
        block = bpy.data.texts.get(obj.get("watercolor_state", ""))
        if block is None:
            raise ValueError("No saved watercolor state; prepare the surface")
        with np.load(
            io.BytesIO(base64.b64decode(block.as_string())), allow_pickle=False
        ) as z:
            meta = json.loads(str(z["meta"]))
            if meta["version"] != 1:
                raise ValueError("Unsupported watercolor state version")
            image = bpy.data.images.get(meta["image"])
            if image is None:
                raise ValueError("Paint image is missing")
            session = cls(
                obj,
                Paint.loads(z["state"].tobytes()),
                z["uvs"].copy(),
                meta["size"],
                image,
                meta["signature"],
            )
            session.history = meta["history"]
            session.undo = [
                (
                    (
                        zlib.decompress(base64.b64decode(str(d)))
                        if meta.get("undo_codec") == "zlib"
                        else base64.b64decode(str(d))
                    ),
                    int(n),
                )
                for d, n in zip(z["undo"], z["undo_lengths"])
            ]
        session.update()
        return session


def get_session(obj):
    if obj is None or obj.type != "MESH" or "watercolor_id" not in obj:
        raise ValueError("Select a prepared mesh")
    key = obj["watercolor_id"]
    if key in SESSIONS and SESSIONS[key].obj != obj:
        raise ValueError(
            "Duplicated paint session: Prepare Surface on this object to make it independent"
        )
    if key not in SESSIONS:
        SESSIONS[key] = Session.restore(obj)
    return SESSIONS[key]


def prepare(obj, settings):
    if obj.type != "MESH" or obj.mode != "OBJECT":
        raise ValueError("Select a mesh in Object Mode")
    if obj.data.shape_keys or any(
        m.show_viewport or m.show_render for m in obj.modifiers
    ):
        raise ValueError(
            "Apply modifiers and shape keys on a copy before preparing this static surface"
        )
    original = obj.data
    if not len(original.polygons):
        raise ValueError("Mesh has no faces")
    # Work on a copy; retain the original mesh with its original material assignments.
    mesh = original.copy()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        if any(not (e.is_manifold or e.is_boundary) for e in bm.edges):
            raise ValueError("Repair loose or nonmanifold edges first")
        if any(not (v.is_manifold or v.is_boundary) for v in bm.verts):
            raise ValueError("Repair nonmanifold vertices first")
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
    finally:
        bm.free()
    v = np.array([obj.matrix_world @ p.co for p in mesh.vertices])
    t = np.array([p.vertices[:] for p in mesh.polygons])
    size = int(settings.resolution)
    uvs = make_uvs(len(t), size)
    surface_uv = mesh.uv_layers.get("Watercolor Canvas") or mesh.uv_layers.new(
        name="Watercolor Canvas"
    )
    for face, uv in zip(mesh.polygons, uvs):
        for loop, value in zip(face.loop_indices, uv):
            surface_uv.data[loop].uv = value
    vertices, triangles, simuv = refine(v, t, uvs, settings.cells)
    paint = Paint(Surface(vertices, triangles), Settings(seed=settings.seed))
    uid = uuid.uuid4().hex[:12]
    image = bpy.data.images.new(
        "Watercolor " + uid, width=size, height=size, alpha=True, float_buffer=True
    )
    image.colorspace_settings.name = "Linear Rec.709"
    image.use_fake_user = True
    material = bpy.data.materials.new("Watercolor Paper " + uid)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    shader.inputs["Roughness"].default_value = 0.9
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Linear"
    texture.extension = "EXTEND"
    uvnode = nodes.new("ShaderNodeUVMap")
    uvnode.uv_map = "Watercolor Canvas"
    links.new(uvnode.outputs["UV"], texture.inputs["Vector"])
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    # A restrained procedural paper micro-normal, independent of pigment transport.
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 180
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    bump.inputs["Distance"].default_value = 0.003
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    mesh.materials.clear()
    mesh.materials.append(material)
    for p in mesh.polygons:
        p.material_index = 0
    original.use_fake_user = True
    obj["watercolor_original_mesh"] = obj.get("watercolor_original_mesh", original.name)
    SESSIONS.pop(obj.get("watercolor_id", ""), None)
    obj.data = mesh
    obj["watercolor_id"] = uid
    session = Session(obj, paint, simuv, size, image, geometry_hash(obj))
    SESSIONS[uid] = session
    apply_settings(session, settings)
    session.update()
    session.store()
    return session


def apply_settings(session, settings):
    p = session.paint.settings
    p.gravity = settings.gravity
    p.absorption = settings.absorption
    p.evaporation = settings.drying
    p.granulation = settings.granulation


def paper_preset(self, context):
    values = {
        "COLD": (0.3, 0.25, 0.8),
        "HOT": (0.4, 0.3, 0.2),
        "ROUGH": (0.18, 0.18, 1.2),
    }
    self.absorption, self.drying, self.granulation = values[self.paper]


class WatercolorSettings(bpy.types.PropertyGroup):
    brush: EnumProperty(
        name="Brush",
        items=[
            ("PIGMENT", "Pigment", "Add water and pigment"),
            ("WATER", "Water", "Rewet and move pigment"),
            ("LIFT", "Lift", "Remove mobile and some settled pigment"),
        ],
        default="PIGMENT",
    )
    pigment: EnumProperty(
        name="Pigment",
        items=[
            ("0", "Rose", "Synthetic rose pigment"),
            ("1", "Blue", "Synthetic blue pigment"),
            ("2", "Ochre", "Synthetic ochre pigment"),
        ],
    )
    paper: EnumProperty(
        name="Paper",
        items=[
            ("COLD", "Cold Press", "Textured absorbent paper"),
            ("HOT", "Hot Press", "Smoother paper"),
            ("ROUGH", "Rough", "Slower absorption and stronger granulation"),
        ],
        update=paper_preset,
    )
    radius: FloatProperty(
        name="Radius", default=0.18, min=0.001, max=100, subtype="DISTANCE"
    )
    water: FloatProperty(name="Water Load", default=0.35, min=0, max=2)
    load: FloatProperty(name="Pigment / Lift", default=0.4, min=0, max=3)
    gravity: FloatProperty(name="Gravity", default=0.1, min=0, max=2)
    absorption: FloatProperty(name="Absorption", default=0.3, min=0, max=1)
    drying: FloatProperty(name="Drying", default=0.25, min=0, max=1)
    granulation: FloatProperty(name="Granulation", default=0.8, min=0, max=2)
    seed: IntProperty(name="Paper Seed", default=22, min=0)
    cells: IntProperty(name="Target Cells", default=20000, min=500, max=50000)
    resolution: EnumProperty(
        name="Texture Size",
        items=[
            ("512", "512", "Fast preview"),
            ("1024", "1024", "Default"),
            ("2048", "2048", "More detail"),
        ],
        default="1024",
    )


class WC_OT_prepare(bpy.types.Operator):
    bl_options = {"REGISTER"}
    bl_idname = "watercolor.prepare"
    bl_label = "Prepare Surface"
    bl_description = "Create a private canvas and porous surface simulation; existing paint on this object is reset"

    def execute(self, context):
        global ACTIVE
        if ACTIVE is not None:
            self.report({"ERROR"}, "Finish painting with Esc before preparing")
            return {"CANCELLED"}
        try:
            if context.object is None:
                raise ValueError("Select a mesh")
            s = prepare(context.object, context.scene.watercolor)
            self.report({"INFO"}, f"Prepared {len(s.paint.water):,} surface cells")
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class WC_OT_action(bpy.types.Operator):
    bl_options = {"REGISTER"}
    bl_idname = "watercolor.action"
    bl_label = "Watercolor Action"
    action: StringProperty()

    def execute(self, context):
        try:
            s = get_session(context.object)
            if self.action != "RESTORE":
                s.check()
            if self.action == "PAUSE":
                if ACTIVE is None:
                    raise ValueError("Start Live Painting before pausing or resuming")
                s.paused = not s.paused
            elif self.action == "UNDO":
                s.undo_stroke()
            elif self.action == "RESET":
                s.begin_stroke()
                s.paint = Paint(s.paint.surface, Settings(**vars(s.paint.settings)))
                s.history.append(dict(action="reset", time=0.0))
                s.update()
            elif self.action == "BAKE":
                s.begin_stroke()
                s.paint.bake()
                s.history.append(dict(action="bake", time=s.paint.time))
                s.update()
            elif self.action == "RESTORE":
                if ACTIVE is not None:
                    raise ValueError(
                        "Finish painting before restoring the original mesh"
                    )
                original = bpy.data.meshes.get(
                    context.object.get("watercolor_original_mesh", "")
                )
                if original is None:
                    raise ValueError("Original mesh is unavailable")
                s.store()
                context.object.data = original
                SESSIONS.pop(context.object["watercolor_id"], None)
                for key in [
                    "watercolor_id",
                    "watercolor_state",
                    "watercolor_original_mesh",
                ]:
                    del context.object[key]
                return {"FINISHED"}
            s.store()
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class WC_OT_paint(bpy.types.Operator):
    bl_options = {"REGISTER"}
    bl_idname = "watercolor.paint"
    bl_label = "Start Live Painting"
    bl_description = "Drag to paint; Space pauses drying; 1/2/3 selects brush; Ctrl Z undoes a stroke; Esc finishes"

    def invoke(self, context, event):
        global ACTIVE
        if ACTIVE is not None:
            self.report({"ERROR"}, "A painting session is already running")
            return {"CANCELLED"}
        try:
            self.session = get_session(context.object)
            self.session.check()
            if context.area.type != "VIEW_3D":
                raise ValueError("Start in a 3D Viewport")
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.area = context.area
        self.region = next(r for r in self.area.regions if r.type == "WINDOW")
        self.rv3d = self.area.spaces.active.region_3d
        self.down = False
        self.last_point = None
        self.last_dab = 0.0
        self.mouse = (0, 0)
        self.timer = context.window_manager.event_timer_add(0.05, window=context.window)
        context.window_manager.modal_handler_add(self)
        ACTIVE = self
        self.session.paused = False
        self.area.spaces.active.shading.type = "MATERIAL"
        context.window.cursor_modal_set("PAINT_BRUSH")
        self.area.header_text_set(
            "Watercolor: drag to paint | Space pause | 1 pigment 2 water 3 lift | Ctrl Z undo | Esc finish"
        )
        return {"RUNNING_MODAL"}

    def hit(self, x, y):
        pos = (x - self.region.x, y - self.region.y)
        if not (0 <= pos[0] < self.region.width and 0 <= pos[1] < self.region.height):
            return None
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, pos)
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, pos)
        point, normal, triangle, distance = self.session.bvh.ray_cast(origin, direction)
        return (triangle, point) if point is not None else None

    def apply_mouse(self, context, event):
        hit = self.hit(*self.mouse)
        if hit is None:
            self.last_point = None
            return
        tri, point = hit
        p = context.scene.watercolor
        now = time.perf_counter()
        if (
            self.last_point is not None
            and (point - self.last_point).length < p.radius * 0.12
            and now - self.last_dab < 0.09
        ):
            return
        strength = 0.25 * max(
            0.05,
            getattr(event, "pressure", 1.0)
            if getattr(event, "is_tablet", False)
            else 1.0,
        )
        self.session.dab(tri, point, p, strength)
        self.last_point = point.copy()
        self.last_dab = now

    def finish(self, context):
        global ACTIVE
        try:
            self.session.paused = True
            self.session.update()
            self.session.store()
        finally:
            try:
                context.window_manager.event_timer_remove(self.timer)
            except (ReferenceError, RuntimeError):
                pass
            if context.window:
                context.window.cursor_modal_restore()
            try:
                self.area.header_text_set(None)
            except ReferenceError:
                pass
            ACTIVE = None

    def modal(self, context, event):
        try:
            if (
                self.session.obj.name not in bpy.data.objects
                or context.object != self.session.obj
            ):
                self.finish(context)
                return {"FINISHED"}
            if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
                self.finish(context)
                return {"FINISHED"}
            if event.type == "SPACE" and event.value == "PRESS":
                self.session.paused = not self.session.paused
                return {"RUNNING_MODAL"}
            if event.type in {"ONE", "TWO", "THREE"} and event.value == "PRESS":
                context.scene.watercolor.brush = {
                    "ONE": "PIGMENT",
                    "TWO": "WATER",
                    "THREE": "LIFT",
                }[event.type]
                return {"RUNNING_MODAL"}
            if event.type == "Z" and event.ctrl and event.value == "PRESS":
                if self.session.undo:
                    self.session.undo_stroke()
                return {"RUNNING_MODAL"}
            if event.type == "TIMER":
                self.session.check()
                apply_settings(self.session, context.scene.watercolor)
                if self.down:
                    self.apply_mouse(context, event)
                self.session.tick()
                if self.session.paused and self.down:
                    self.session.update()
                self.area.tag_redraw()
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE":
                # Sidebar buttons retain normal interaction.
                if event.value == "PRESS":
                    if self.hit(event.mouse_x, event.mouse_y) is None:
                        return {"PASS_THROUGH"}
                    self.down = True
                    self.last_point = None
                    self.session.begin_stroke()
                    self.mouse = (event.mouse_x, event.mouse_y)
                    self.apply_mouse(context, event)
                else:
                    self.down = False
                return {"RUNNING_MODAL"}
            if event.type == "MOUSEMOVE":
                previous = self.mouse
                current = (event.mouse_x, event.mouse_y)
                if self.down:
                    count = min(
                        48,
                        max(
                            1,
                            int(
                                np.hypot(
                                    current[0] - previous[0], current[1] - previous[1]
                                )
                                / 4
                            ),
                        ),
                    )
                    for k in range(1, count + 1):
                        f = k / count
                        self.mouse = (
                            previous[0] + f * (current[0] - previous[0]),
                            previous[1] + f * (current[1] - previous[1]),
                        )
                        self.apply_mouse(context, event)
                    return {"RUNNING_MODAL"}
                self.mouse = current
            return {"PASS_THROUGH"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            self.finish(context)
            return {"CANCELLED"}


class WC_OT_export(bpy.types.Operator, ExportHelper):
    bl_options = {"REGISTER"}
    bl_idname = "watercolor.export"
    bl_label = "Export Paint Texture"
    filename_ext = ".png"
    filter_glob: StringProperty(default="*.png", options={"HIDDEN"})

    def execute(self, context):
        try:
            s = get_session(context.object)
            s.update()
            # Save texture data, independent of the scene's display/view transform.
            old_format = s.image.file_format
            try:
                s.image.file_format = "PNG"
                s.image.save(filepath=self.filepath, save_copy=True)
            finally:
                s.image.file_format = old_format
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class WC_PT_panel(bpy.types.Panel):
    bl_label = "Blender Watercolor"
    bl_idname = "WC_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Watercolor"

    def draw(self, context):
        l = self.layout
        p = context.scene.watercolor
        l.label(text="Paint on porous surfaces")
        box = l.box()
        box.prop(p, "cells")
        box.prop(p, "resolution")
        box.prop(p, "seed")
        box.operator("watercolor.prepare")
        if not context.object or "watercolor_id" not in context.object:
            return
        l.prop(p, "brush", expand=True)
        l.prop(p, "pigment")
        l.prop(p, "paper")
        l.prop(p, "radius")
        l.prop(p, "water")
        l.prop(p, "load")
        l.prop(p, "gravity")
        l.prop(p, "absorption")
        l.prop(p, "drying")
        l.prop(p, "granulation")
        l.operator("watercolor.paint")
        row = l.row()
        row.operator("watercolor.action", text="Pause / Resume").action = "PAUSE"
        row.operator("watercolor.action", text="Undo Stroke").action = "UNDO"
        row = l.row()
        row.operator("watercolor.action", text="Reset").action = "RESET"
        row.operator("watercolor.action", text="Bake Layer").action = "BAKE"
        l.operator("watercolor.export")
        l.operator("watercolor.action", text="Restore Original").action = "RESTORE"
        l.label(text="Esc finishes • Space pauses")
        key = context.object.get("watercolor_id")
        s = SESSIONS.get(key)
        if s:
            l.label(
                text=f"{len(s.paint.water):,} cells • {s.paint.time:.2f} s"
                + (" • paused" if s.paused else "")
            )


@persistent
def save_state(_):
    for s in list(SESSIONS.values()):
        try:
            if s.obj.name in bpy.data.objects:
                s.store()
        except Exception as e:
            print("Watercolor save error:", e)


@persistent
def clear_state(_):
    global ACTIVE
    if ACTIVE is not None:
        try:
            ACTIVE.finish(bpy.context)
        except (ReferenceError, RuntimeError):
            pass
    SESSIONS.clear()
    ACTIVE = None


CLASSES = (
    WatercolorSettings,
    WC_OT_prepare,
    WC_OT_action,
    WC_OT_paint,
    WC_OT_export,
    WC_PT_panel,
)


def object_menu(self, context):
    self.layout.separator()
    self.layout.operator("watercolor.prepare")
    self.layout.operator("watercolor.paint")


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.watercolor = PointerProperty(type=WatercolorSettings)
    bpy.types.VIEW3D_MT_object.append(object_menu)
    bpy.app.handlers.save_pre.append(save_state)
    bpy.app.handlers.load_pre.append(clear_state)


def unregister():
    global ACTIVE
    if ACTIVE is not None:
        ACTIVE.finish(bpy.context)
    for handlers, fn in (
        (bpy.app.handlers.save_pre, save_state),
        (bpy.app.handlers.load_pre, clear_state),
    ):
        if fn in handlers:
            handlers.remove(fn)
    SESSIONS.clear()
    bpy.types.VIEW3D_MT_object.remove(object_menu)
    del bpy.types.Scene.watercolor
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
