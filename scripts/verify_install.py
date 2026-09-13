"""Verify an extracted extension ZIP in an isolated Blender process.

Uses Blender's extension installer, a local repository and an isolated user
configuration. No user preferences are modified by this verification script.
"""

import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import bpy

repo = ROOT / "build/test-extensions"
repo.mkdir(parents=True, exist_ok=True)
bpy.ops.preferences.extension_repo_add(
    name="Watercolor Test",
    use_custom_directory=True,
    custom_directory=str(repo),
    type="LOCAL",
)
r = bpy.context.preferences.extensions.repos[-1]
print("TEST REPOSITORY", r.module)
result = bpy.ops.extensions.package_install_files(
    filepath=str(ROOT / "dist/blender_watercolor-0.1.0.zip"),
    repo=r.module,
    enable_on_install=True,
)
assert result == {"FINISHED"}, result
assert hasattr(bpy.types, "WC_PT_panel")
assert hasattr(bpy.context.scene, "watercolor")
bpy.ops.mesh.primitive_grid_add(x_subdivisions=6, y_subdivisions=6, size=2)
bpy.context.scene.watercolor.cells = 500
bpy.context.scene.watercolor.resolution = "512"
assert bpy.ops.watercolor.prepare() == {"FINISHED"}
assert bpy.context.object.get("watercolor_state")
import importlib, numpy as np

addon = importlib.import_module("bl_ext." + r.module + ".blender_watercolor.addon")
obj = bpy.context.object
s = addon.get_session(obj)
s.begin_stroke()
s.paint.apply([10, 11], [1, 0.5])
s.update()
original = s.paint.dumps()
history = list(s.history)
assert bpy.ops.watercolor.action(action="BAKE") == {"FINISHED"}
assert bpy.ops.watercolor.action(action="UNDO") == {"FINISHED"}
np.testing.assert_array_equal(addon.Paint.loads(original).mobile, s.paint.mobile)
assert bpy.ops.watercolor.action(action="RESET") == {"FINISHED"}
assert bpy.ops.watercolor.action(action="UNDO") == {"FINISHED"}
np.testing.assert_array_equal(addon.Paint.loads(original).mobile, s.paint.mobile)
assert s.history == history
s.store()
restored = addon.Session.restore(obj)
np.testing.assert_array_equal(restored.paint.mobile, s.paint.mobile)
assert restored.undo == s.undo
assert restored.history == s.history
export = ROOT / "build/export-test.png"
old_view = bpy.context.scene.view_settings.view_transform
bpy.context.scene.view_settings.view_transform = "AgX"
assert bpy.ops.watercolor.export(filepath=str(export)) == {"FINISHED"}
assert export.read_bytes().startswith(b"\x89PNG")
bpy.context.scene.view_settings.view_transform = old_view
# Reprepare must not keep a stale session writing over this object's new state.
assert bpy.ops.watercolor.prepare() == {"FINISHED"}
assert len(addon.SESSIONS) == 1
assert bpy.ops.watercolor.action(action="RESTORE") == {"FINISHED"}
assert "watercolor_id" not in obj
assert len(addon.SESSIONS) == 0
(ROOT / "build/verification-install.json").write_text(
    json.dumps(
        {
            "installed_from_zip": True,
            "enabled": True,
            "prepare_operator": True,
            "bake_reset_undo": True,
            "export_png": True,
            "reprepare_restore": True,
            "blender": bpy.app.version_string,
        },
        indent=2,
    )
)
print("INSTALL PASS")
