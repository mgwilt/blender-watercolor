# Original examples

Run `scripts/verify_blender.py` with Blender to generate a flat sheet, a curved sheet and a sphere with synthetic pigment washes. The script creates `build/watercolor-demo.blend`, actual EEVEE/Cycles renders and verification reports.

Run `scripts/drying_demo.py` after generating the scene to render a drying sequence. This is accelerated model time, not a real-time benchmark.

For a compact interactive development window:

```sh
blender --factory-startup --window-geometry 80 120 1280 850 --python scripts/gui_preview.py
```

All example geometry and imagery are newly generated from elementary shapes. They are CC0 and contain no external artwork or models.
