"""Measure numerical simulation and geodesic brush cost without Blender."""

import sys, time, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from blender_watercolor.core.surface import Surface, Paint

n = 142
y, x = np.mgrid[:n, :n] / (n - 1)
v = np.column_stack([x.ravel(), y.ravel(), 0.15 * np.sin(x.ravel() * 4)])
a = np.arange(n * n).reshape(n, n)[:-1, :-1].ravel()
t = np.concatenate(
    [np.stack([a, a + 1, a + n], 1), np.stack([a + 1, a + n + 1, a + n], 1)]
)
start = time.perf_counter()
s = Surface(v, t)
p = Paint(s)
prep = time.perf_counter() - start
brush = []
for k in range(10):
    start = time.perf_counter()
    ids, w = s.footprint(len(t) // 2 + k, v[t[len(t) // 2 + k]].mean(0), 0.08)
    p.apply(ids, w)
    brush.append(time.perf_counter() - start)
steps = []
for _ in range(50):
    start = time.perf_counter()
    p.step()
    steps.append(time.perf_counter() - start)
print(
    json.dumps(
        dict(
            cells=len(v),
            prepare_seconds=prep,
            step_median_ms=float(np.median(steps) * 1000),
            step_max_ms=max(steps) * 1000,
            brush_max_ms=max(brush) * 1000,
            conservation=p.report(),
        ),
        indent=2,
    )
)
