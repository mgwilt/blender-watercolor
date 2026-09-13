# Validation for 0.1.0

Verified with Blender 5.2.0 LTS (`fbe6228777e7`) on an Apple M3 Ultra running macOS ARM64. Other platforms are not runtime-verified. The code has no platform-specific numerical dependencies beyond Blender's bundled NumPy.

## Automated checks

- 21 numerical tests: ten retained planar baseline tests and eleven surface tests.
- Surface mass accounting, nonnegative stores, flat equilibrium, half-turn symmetry, gravity, wet versus dry substrate, seam-independent connectivity, disconnected-sheet isolation and a smooth refinement case.
- Water-only rewetting, lifting, optical baking/glazes and exact numerical save/resume.
- Installation and enablement from the distributable ZIP in an isolated Blender configuration.
- Real Blender operators: prepare, bake/reset and stroke undo, PNG export, reprepare and restore original.
- Saved plane, curved sheet and sphere reopen with exact simulation arrays and exact canvas pixels, then continue simulation.
- Original vertex coordinates and existing UV-map availability checked after preparation. Display UVs have deliberately separate face islands while transport remains connected.
- Actual EEVEE and Cycles renders of original procedural surfaces.

## Interactive check

Operated the extension in a small Blender window using actual mouse drags: opened the panel, started painting, added pigment and water, paused/resumed, lifted, undid a stroke and finished. A fast diagonal stroke was rechecked after adding interpolation between mouse events. The resulting scene was saved separately and reopened to inspect added brush records, state and conservation.

## Performance

Measured using a 1024-pixel atlas, including solver work and Blender image updates:

| Surface | Cells | Median update | Updates/second | Maximum brush sampling |
|---|---:|---:|---:|---:|
| Flat sheet | 21,025 | 68.0 ms | 14.7 | 3.84 ms |
| Curved sheet | 21,025 | 68.2 ms | 14.7 | 3.41 ms |
| Sphere | 16,898 | 67.3 ms | 14.9 | 1.50 ms |

A separate first-stroke test including the undo snapshot, brush sampling, injection, optics and Blender image update measured 43.5 ms median and 46.3 ms maximum on 21,025 cells. OS event delivery and viewport draw are excluded.

These are local test measurements, not guaranteed rates. Brush numbers measure geodesic sampling and injection; an image refresh takes an additional update. Modal event scheduling, snapshot creation, viewport rendering and slower hardware can add latency. Model time slows under load.

## Visual scope

The rendered studies show uneven deposition, visible pigment edges and translucent overlapping washes on flat and curved surfaces. The result remains experimental: graph-direction bias can make circular footprints angular, granulation is empirical and fine detail depends on cell resolution. Neither bookkeeping nor these images establishes experimentally calibrated fluid behavior or a professional watercolor match.

## Reproduction

Run the commands in the README. Detailed machine-generated reports are produced under `build/`, including `benchmark.json`, `verification-before.json`, `verification-reopen.json` and `verification-install.json`. `scripts/drying_demo.py` renders an original drying sequence. The interactive evidence checker requires the separately saved manual test scene; it is not part of the headless test suite.
