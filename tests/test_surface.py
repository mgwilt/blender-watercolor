import unittest
import numpy as np
from blender_watercolor.core.surface import Surface, Paint, Settings


def grid(n=12, curve=False, offset=0):
    x, y = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n))
    z = 0.2 * np.sin(x * 3) if curve else np.zeros_like(x)
    vertices = np.column_stack([x.ravel() + offset, y.ravel(), z.ravel()])
    faces = []
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i
            faces.extend([(a, a + 1, a + n), (a + 1, a + n + 1, a + n)])
    return vertices, np.array(faces)


class SurfaceTests(unittest.TestCase):
    def test_mass_and_drying(self):
        p = Paint(Surface(*grid()), Settings(evaporation=0.1))
        p.apply([65], [1], water=0.1)
        for _ in range(400):
            p.step()
        r = p.report()
        self.assertLess(abs(r["water_error"]), 1e-12)
        self.assertLess(max(abs(np.array(r["pigment_error"]))), 1e-12)
        self.assertGreater(p.fixed.sum(), 0)
        self.assertGreaterEqual(p.water.min(), 0)

    def test_flat_equilibrium(self):
        p = Paint(Surface(*grid()), Settings(absorption=0, evaporation=0, gravity=0))
        p.water.fill(0.2)
        for _ in range(40):
            p.step()
        self.assertLess(np.ptp(p.water), 1e-13)

    def test_disconnected_geodesic_and_transport(self):
        a, t = grid(6)
        b, u = grid(6)
        b[:, 2] += 0.001
        s = Surface(np.concatenate([a, b]), np.concatenate([t, u + len(a)]))
        p = Paint(s)
        ids, w = s.footprint(0, a[t[0]].mean(0), 3)
        self.assertTrue(np.all(ids < len(a)))
        p.apply(ids, w)
        for _ in range(100):
            p.step()
        self.assertEqual(p.water[len(a) :].sum(), 0)
        self.assertEqual(p.mobile[:, len(a) :].sum(), 0)

    def test_connectivity_ignores_uv_seams(self):
        # UVs never enter Surface: transport crosses a conceptual seam at x=.5.
        s = Surface(*grid(12))
        p = Paint(s, Settings(absorption=0, evaporation=0, gravity=0))
        left = np.flatnonzero((s.vertices[:, 0] < 0.5) & (s.vertices[:, 0] > 0.35))
        p.apply(left, np.ones(len(left)))
        for _ in range(100):
            p.step()
        self.assertGreater(p.mobile[:, s.vertices[:, 0] > 0.5].sum(), 0)

    def test_gravity_flows_down_curved_surface(self):
        s = Surface(*grid(14, True))
        p = Paint(s, Settings(absorption=0, evaporation=0, gravity=0.5))
        p.water.fill(0.2)
        before = float((p.water * s.area) @ s.xyz[:, 2])
        for _ in range(100):
            p.step()
        self.assertLess(float((p.water * s.area) @ s.xyz[:, 2]), before)

    def test_rewet_lift_and_glaze(self):
        s = Surface(*grid())
        p = Paint(s)
        ids = np.arange(len(p.water))
        weights = np.ones(len(ids))
        p.apply(ids, weights, water=0, load=0.5)
        p.step()
        self.assertEqual(p.mobile.sum(), 0)
        p.apply(ids, weights, mode="WATER", water=0.5)
        p.step()
        self.assertGreater(p.mobile.sum(), 0)
        before = (p.mobile + p.fixed).sum()
        p.apply(ids, weights, mode="LIFT", load=0.4)
        self.assertLess((p.mobile + p.fixed).sum(), before)
        self.assertLess(max(abs(np.array(p.report()["pigment_error"]))), 1e-12)
        color = p.colors()
        p.bake()
        np.testing.assert_allclose(p.colors(), color, atol=1e-12)
        p.apply(ids, weights, pigment=1, water=0, load=0.4)
        self.assertFalse(np.allclose(p.colors(), color))

    def test_save_resume_exact(self):
        p = Paint(Surface(*grid(9, True)))
        p.apply([20, 21], [1, 0.5])
        for _ in range(8):
            p.step()
        q = Paint.loads(p.dumps(compress=False))
        for _ in range(12):
            p.step()
            q.step()
        np.testing.assert_array_equal(p.water, q.water)
        np.testing.assert_array_equal(p.mobile, q.mobile)
        self.assertEqual(p.report(), q.report())

    def test_refinement_and_symmetry(self):
        results = []
        for n in (12, 24, 48):
            s = Surface(*grid(n))
            p = Paint(s, Settings(absorption=0, evaporation=0, gravity=0))
            p.water = 0.1 + 0.05 * np.cos(np.pi * s.xyz[:, 0] / s.xyz[:, 0].max())
            until = 0.3
            while p.time < until - 1e-12:
                p.step(min(p.stable_dt(), until - p.time))
            results.append(float((p.water * s.area) @ s.xyz[:, 0] / s.area.sum()))
        self.assertLess(abs(results[2] - results[1]), abs(results[1] - results[0]))
        self.assertLess(abs(results[2] - results[1]), 0.001)

    def test_wet_paper_changes_flow(self):
        surface = Surface(*grid(14))
        states = []
        for prewet in (False, True):
            p = Paint(surface, Settings(gravity=0, evaporation=0))
            if prewet:
                p.absorbed = p.settings.capacity * (0.7 + 0.6 * p.paper) * 0.95
                p.water_input = float(p.absorbed @ surface.area)
            p.apply([90, 91], [1, 1], water=0.25, load=0.6)
            for _ in range(100):
                p.step()
            self.assertLess(abs(p.report()["water_error"]), 1e-12)
            states.append(p)
        self.assertFalse(np.allclose(states[0].mobile, states[1].mobile))

    def test_surface_half_turn_symmetry(self):
        n = 14
        s = Surface(*grid(n))
        p = Paint(
            s, Settings(gravity=0, absorption=0, evaporation=0, deposit=0, release=0)
        )
        x = s.vertices[:, 0]
        y = s.vertices[:, 1]
        p.water = 0.2 * np.exp(-((x - 0.5) ** 2 + (y - 0.5) ** 2) / 0.05)
        for _ in range(80):
            p.step()
        np.testing.assert_allclose(
            p.water.reshape(n, n), p.water.reshape(n, n)[::-1, ::-1], atol=1e-12
        )

    def test_invalid_geometry_and_timestep(self):
        v, t = grid()
        with self.assertRaises(ValueError):
            Surface(v, np.concatenate([t, t[:1], t[:1]]))
        p = Paint(Surface(v, t))
        with self.assertRaises(ValueError):
            p.step(100)
        with self.assertRaises(ValueError):
            p.apply([1], [1], load=-1)


if __name__ == "__main__":
    unittest.main()
