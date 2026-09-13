"""Open the original demo for interactive verification."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy

bpy.ops.wm.open_mainfile(filepath=str(ROOT / "build/watercolor-demo.blend"))
import blender_watercolor

blender_watercolor.register()
# Tools are operated manually from the Watercolor panel or F3 search.
