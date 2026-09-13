import unittest
import numpy as np
from blender_watercolor.core.planar import Wash, Parameters, km_layer, render


class SolverTests(unittest.TestCase):
    def test_permeability_resists_and_conserves_flow(self):
        results = []
        for resistance in [1, 0.01]:
            perm = np.ones((16, 16))
            perm[:, 8:] = resistance
            w = Wash(
                16, Parameters(evaporation=0, edge_evaporation=0), permeability=perm
            )
            mask = np.zeros((16, 16))
            mask[:, :8] = 1
            w.add(mask, 0.008, prewet=True)
            for _ in range(20):
                w.step()
            results.append(w.saturation[:, 8:].sum())
            self.assertLess(abs(w.report()["water_error"]), 1e-12)
        self.assertLess(results[1], results[0] * 0.1)

    def test_invalid_permeability_rejected(self):
        with self.assertRaises(ValueError):
            Wash(16, permeability=np.full((16, 16), np.nan))

    def test_reconstructed_coupled_mass(self):
        w = Wash(32, Parameters(reconstructed_transport=True))
        y, x = np.mgrid[:32, :32] / 32
        mask = (x - 0.5) ** 2 + (y - 0.5) ** 2 < 0.1
        w.add(mask, 0.03, [0.4, 0.2])
        for _ in range(300):
            w.step()
        r = w.report()
        self.assertLess(abs(r["water_error"]), 1e-12)
        self.assertLess(max(abs(np.array(r["pigment_error"]))), 1e-12)
        self.assertGreaterEqual(w.mobile.min(), 0)

    def test_closed_mass_and_drying(self):
        w = Wash(32)
        y, x = np.mgrid[:32, :32] / 32
        mask = (x - 0.5) ** 2 + (y - 0.5) ** 2 < 0.1
        w.add(mask, 0.03, [0.4, 0.2])
        for _ in range(300):
            w.step()
        r = w.report()
        self.assertLess(abs(r["water_error"]), 1e-12)
        self.assertLess(max(abs(np.array(r["pigment_error"]))), 1e-12)
        self.assertGreater(w.evaporated, 0)
        self.assertGreater(w.saturation.sum(), 0)
        self.assertGreater(w.fixed.sum(), 0)
        self.assertLessEqual(w.saturation.max(), w.capacity.max() + 1e-12)

    def test_constant_equilibrium(self):
        p = Parameters(evaporation=0, edge_evaporation=0, absorption=0, paper_relief=0)
        w = Wash(24, p)
        w.add(np.ones((24, 24)), 0.02, [0.2, 0.1])
        for _ in range(40):
            w.step()
        self.assertLess(np.ptp(w.water), 1e-13)
        self.assertLess(abs(w.u).max(), 1e-13)

    def test_symmetric_transport(self):
        w = Wash(32, paper=np.ones((32, 32)) * 0.5)
        y, x = np.mgrid[:32, :32]
        mask = (x - 15.5) ** 2 + (y - 15.5) ** 2 < 80
        w.add(mask, 0.03, [0.4, 0.2])
        for _ in range(100):
            w.step()
        np.testing.assert_allclose(w.water, w.water[::-1, :], atol=1e-12)
        np.testing.assert_allclose(w.mobile, w.mobile[:, :, ::-1], atol=1e-12)

    def test_identical_pigment_split_glaze(self):
        # A homogeneous optical layer must be invariant to splitting its thickness.
        pigment = [dict(K=[0.14, 1.08, 1.68], S=[0.77, 0.015, 0.018])]
        thickness = np.linspace(0, 4, 64).reshape(1, 8, 8)
        r, t = km_layer(thickness, pigment)
        rh, th = km_layer(thickness / 2, pigment)
        bg = np.array([0.74, 0.76, 0.65])

        def over(r, t, b):
            return r + t * t * b / (1 - r * b)

        np.testing.assert_allclose(
            over(r, t, bg), over(rh, th, over(rh, th, bg)), atol=2e-14
        )

    def test_km_limits_and_energy(self):
        zero = np.zeros((2, 8, 8))
        r, t = km_layer(zero)
        np.testing.assert_equal(r, 0)
        np.testing.assert_equal(t, 1)
        r, t = km_layer(np.ones((2, 8, 8)) * 0.6)
        self.assertTrue(np.all(r + t <= 1 + 1e-12))
        self.assertTrue(np.all(r >= 0))
        self.assertTrue(np.all(t >= 0))

    def test_pure_scattering_limit(self):
        pigment = [dict(K=[0, 0, 0], S=[1, 1, 1])]
        r, t = km_layer(np.ones((1, 2, 2)), pigment)
        np.testing.assert_allclose(r, 0.5)
        np.testing.assert_allclose(t, 0.5)

    def test_drying_does_not_destroy_pigment(self):
        w = Wash(16, Parameters(evaporation=0.04))
        w.add(np.ones((16, 16)), 0.002, [0.1, 0.3])
        for _ in range(40):
            w.step()
        self.assertLess(w.water.sum(), 1e-12)
        self.assertLess(w.mobile.sum(), 1e-12)
        np.testing.assert_allclose(w.fixed.mean(axis=(1, 2)), [0.1, 0.3], atol=1e-12)


if __name__ == "__main__":
    unittest.main()
