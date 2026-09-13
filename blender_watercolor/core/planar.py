"""Conservative research prototype for water/pigment on paper.

Layer architecture and KM optics: Curtis et al. SIGGRAPH1997 §§4–5.
Dynamics deviation: linear damped shallow water, not Curtis' projected MAC
scheme. This baseline is retained for numerical regression tests.
All quantities use a nondimensional unit-square paper domain.
"""

from dataclasses import dataclass, asdict
import numpy as np


@dataclass
class Parameters:
    gravity: float = 0.08
    drag: float = 7.0
    viscosity: float = 0.00004
    evaporation: float = 0.0011
    edge_evaporation: float = 0.0035
    edge_width: float = 0.025
    absorption: float = 0.002
    capillary_diffusion: float = 0.00012
    pigment_diffusion: float = 0.000008
    paper_relief: float = 0.0008
    capacity: float = 0.012
    wet_threshold: float = 0.72
    dt: float = 0.004
    reconstructed_transport: bool = False


# Curtis Fig5 synthetic coefficients, not measured spectral pigment data.
PIGMENTS = [
    dict(
        name="Quinacridone Rose (Curtis synthetic)",
        K=[0.22, 1.47, 0.57],
        S=[0.05, 0.003, 0.03],
        rho=0.02,
        omega=5.5,
        gamma=0.81,
    ),
    dict(
        name="Cerulean Blue (Curtis synthetic)",
        K=[1.52, 0.32, 0.25],
        S=[0.06, 0.26, 0.40],
        rho=0.01,
        omega=1.0,
        gamma=0.31,
    ),
]


def paper_field(n, seed=22, max_frequency=65):
    """Continuous Fourier paper; shared seed admits sampling at multiple grids."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[:n, :n] / n
    z = np.zeros((n, n))
    for _ in range(60):
        kx, ky = rng.integers(-max_frequency, max_frequency + 1, size=2)
        phase = rng.uniform(0, 2 * np.pi)
        z += (
            np.cos(2 * np.pi * (kx * x + ky * y) + phase)
            / max(4, np.hypot(kx, ky)) ** 0.65
        )
    return np.clip(0.5 + z * 0.055, 0, 1)


def totals_out(fx, fy):
    return (
        np.maximum(fx[:, 1:], 0)
        + np.maximum(-fx[:, :-1], 0)
        + np.maximum(fy[1:, :], 0)
        + np.maximum(-fy[:-1, :], 0)
    )


def bound_out(fx, fy, available):
    """Bound simultaneous donor transfers; every face remains antisymmetric."""
    out = totals_out(fx, fy)
    scale = np.minimum(1, available / np.maximum(out, 1e-30))
    fx = fx.copy()
    fy = fy.copy()
    fx[:, 1:-1] *= np.where(fx[:, 1:-1] >= 0, scale[:, :-1], scale[:, 1:])
    fy[1:-1, :] *= np.where(fy[1:-1, :] >= 0, scale[:-1, :], scale[1:, :])
    return fx, fy


def divergence(fx, fy):
    return fx[:, 1:] - fx[:, :-1] + fy[1:, :] - fy[:-1, :]


def donor_flux(fx, fy, concentration):
    px = np.zeros_like(fx)
    py = np.zeros_like(fy)
    px[:, 1:-1] = fx[:, 1:-1] * np.where(
        fx[:, 1:-1] >= 0, concentration[:, :-1], concentration[:, 1:]
    )
    py[1:-1, :] = fy[1:-1, :] * np.where(
        fy[1:-1, :] >= 0, concentration[:-1, :], concentration[1:, :]
    )
    return px, py


def reconstructed_flux(fx, fy, concentration, water):
    """Minmod face reconstruction with donor Courant correction.

    Conservative bounded face flux; 1-D accuracy tested separately. No blanket
    multidimensional TVD claim for the coupled variable-depth implementation.
    """

    def minmod(a, b):
        return np.where(a * b > 0, np.sign(a) * np.minimum(abs(a), abs(b)), 0)

    sx = np.zeros_like(concentration)
    sy = np.zeros_like(concentration)
    sx[:, 1:-1] = minmod(
        concentration[:, 1:-1] - concentration[:, :-2],
        concentration[:, 2:] - concentration[:, 1:-1],
    )
    sy[1:-1, :] = minmod(
        concentration[1:-1, :] - concentration[:-2, :],
        concentration[2:, :] - concentration[1:-1, :],
    )
    px = np.zeros_like(fx)
    py = np.zeros_like(fy)
    for f, q, slope, w, axis in [
        (fx, concentration, sx, water, 1),
        (fy, concentration, sy, water, 0),
    ]:
        left = (
            (slice(None), slice(None, -1)) if axis else (slice(None, -1), slice(None))
        )
        right = (slice(None), slice(1, None)) if axis else (slice(1, None), slice(None))
        interior = (slice(None), slice(1, -1)) if axis else (slice(1, -1), slice(None))
        ff = f[interior]
        positive = ff >= 0
        wd = np.where(positive, w[left], w[right])
        courant = np.minimum(1, abs(ff) / np.maximum(wd, 1e-20))
        value = np.where(
            positive,
            q[left] + 0.5 * (1 - courant) * slope[left],
            q[right] - 0.5 * (1 - courant) * slope[right],
        )
        target = px if axis else py
        target[interior] = ff * np.maximum(value, 0)
    return bound_out(px, py, concentration * water)


class Wash:
    def __init__(
        self, n=128, params=None, paper=None, pigments=None, permeability=None
    ):
        self.n = n
        self.dx = 1 / n
        self.p = params or Parameters()
        self.paper = paper_field(n) if paper is None else paper.copy()
        self.capacity = self.p.capacity * (0.75 + 0.5 * self.paper)
        self.permeability = (
            np.ones((n, n)) if permeability is None else np.asarray(permeability).copy()
        )
        if (
            self.permeability.shape != (n, n)
            or not np.isfinite(self.permeability).all()
            or np.any(self.permeability <= 0)
        ):
            raise ValueError("Permeability must be positive and grid-shaped")
        self.pigments = pigments or PIGMENTS
        self.water = np.zeros((n, n))
        self.saturation = np.zeros((n, n))
        self.mobile = np.zeros((len(self.pigments), n, n))
        self.fixed = self.mobile.copy()
        self.u = np.zeros((n, n + 1))
        self.v = np.zeros((n + 1, n))
        self.wet = np.zeros((n, n), bool)
        self.time = 0.0
        self.evaporated = 0.0
        self.input_water = 0.0
        self.input_pigment = np.zeros(len(self.pigments))
        self.roundoff_correction = 0.0
        self.max_flux_limited_fraction = 0.0

    def add(self, mask, water, pigment=None, prewet=False):
        amount = np.maximum(mask, 0) * water
        if prewet:
            accepted = np.minimum(
                amount, np.maximum(self.capacity - self.saturation, 0)
            )
            self.saturation += accepted
            self.input_water += accepted.sum() * self.dx**2
        else:
            self.water += amount
            self.wet |= amount > 1e-12
            self.input_water += amount.sum() * self.dx**2
        if pigment is not None:
            for k, pig in enumerate(pigment):
                mass = np.maximum(mask, 0) * pig
                self.mobile[k] += mass
                self.input_pigment[k] += mass.sum() * self.dx**2

    def step(self, dt=None):
        p = self.p
        dt = p.dt if dt is None else dt
        dx = self.dx
        speed = max(np.max(abs(self.u)), np.max(abs(self.v))) + np.sqrt(
            p.gravity * np.max(self.water)
        )
        if dt * speed / dx > 0.35:
            raise ValueError("CFL exceeded: reduce dt")
        if (
            dt
            * max(
                p.capillary_diffusion * self.permeability.max(),
                p.pigment_diffusion,
                p.viscosity,
            )
            / dx**2
            > 0.20
        ):
            raise ValueError("Diffusive timestep exceeded")
        self.wet |= self.saturation > self.capacity * p.wet_threshold
        # Edge-dependent evaporation drives a water-height deficit, not a painted rim.
        edge = np.zeros_like(self.water)
        for shift in range(1, max(2, round(p.edge_width / dx)) + 1):
            padded = np.pad(self.wet, shift, constant_values=False)
            for dy, dxs in [(0, shift), (0, -shift), (shift, 0), (-shift, 0)]:
                edge += (
                    ~padded[
                        shift + dy : shift + dy + self.n,
                        shift + dxs : shift + dxs + self.n,
                    ]
                ) * np.exp(-shift * dx / p.edge_width)
        edge /= max(float(edge.max()), 1.0)
        evap = np.minimum(self.water, dt * (p.evaporation + p.edge_evaporation * edge))
        self.water -= evap
        self.evaporated += evap.sum() * dx**2
        evap_paper = np.minimum(self.saturation, dt * p.evaporation * 0.3)
        self.saturation -= evap_paper
        self.evaporated += evap_paper.sum() * dx**2
        # Linear momentum response on staggered faces; no nonlinear convection.
        head = self.water + p.paper_relief * self.paper
        for velocity in [self.u, self.v]:
            padded = np.pad(velocity, 1, mode="edge")
            lap = (
                padded[1:-1, 2:]
                + padded[1:-1, :-2]
                + padded[2:, 1:-1]
                + padded[:-2, 1:-1]
                - 4 * velocity
            ) / dx**2
            velocity += dt * (p.viscosity * lap - p.drag * velocity)
        self.u[:, 1:-1] -= dt * p.gravity * np.diff(head, axis=1) / dx
        self.v[1:-1, :] -= dt * p.gravity * np.diff(head, axis=0) / dx
        self.u[:, [0, -1]] = 0
        self.v[[0, -1], :] = 0
        self.u[:, 1:-1] *= self.wet[:, :-1] & self.wet[:, 1:]
        self.v[1:-1, :] *= self.wet[:-1, :] & self.wet[1:, :]
        fx, fy = donor_flux(self.u * dt / dx, self.v * dt / dx, self.water)
        raw = totals_out(fx, fy)
        self.max_flux_limited_fraction = max(
            self.max_flux_limited_fraction, float(np.mean(raw > self.water))
        )
        fx, fy = bound_out(fx, fy, self.water * 0.95)
        for k in range(len(self.pigments)):
            concentration = np.divide(
                self.mobile[k],
                self.water,
                out=np.zeros_like(self.water),
                where=self.water > 1e-14,
            )
            px, py = (
                reconstructed_flux(fx, fy, concentration, self.water)
                if p.reconstructed_transport
                else donor_flux(fx, fy, concentration)
            )
            self.mobile[k] -= divergence(px, py)
        self.water -= divergence(fx, fy)
        # Absorption is an actual transfer into paper, with finite capacity.
        absorb = np.minimum(
            self.water,
            np.minimum(
                dt * p.absorption, np.maximum(self.capacity - self.saturation, 0)
            ),
        )
        self.water -= absorb
        self.saturation += absorb
        cx = np.zeros_like(self.u)
        cy = np.zeros_like(self.v)
        cx[:, 1:-1] = (
            -p.capillary_diffusion * dt / dx**2 * np.diff(self.saturation, axis=1)
        )
        cy[1:-1, :] = (
            -p.capillary_diffusion * dt / dx**2 * np.diff(self.saturation, axis=0)
        )
        # Harmonic face permeability: a low-permeability cell limits pore flux.
        perm = self.permeability
        cx[:, 1:-1] *= 2 * perm[:, :-1] * perm[:, 1:] / (perm[:, :-1] + perm[:, 1:])
        cy[1:-1, :] *= 2 * perm[:-1, :] * perm[1:, :] / (perm[:-1, :] + perm[1:, :])
        cx, cy = bound_out(cx, cy, self.saturation)
        # Receiver-space limiting by reversing transfers; preserves pairwise balance.
        cx, cy = bound_out(-cx, -cy, np.maximum(self.capacity - self.saturation, 0))
        cx = -cx
        cy = -cy
        self.saturation -= divergence(cx, cy)
        for k, pig in enumerate(self.pigments):
            mx = np.zeros_like(self.u)
            my = np.zeros_like(self.v)
            mx[:, 1:-1] = (
                -p.pigment_diffusion
                * dt
                / dx**2
                * np.diff(self.mobile[k], axis=1)
                * (self.water[:, :-1] > 1e-5)
                * (self.water[:, 1:] > 1e-5)
            )
            my[1:-1, :] = (
                -p.pigment_diffusion
                * dt
                / dx**2
                * np.diff(self.mobile[k], axis=0)
                * (self.water[:-1, :] > 1e-5)
                * (self.water[1:, :] > 1e-5)
            )
            mx, my = bound_out(mx, my, self.mobile[k])
            self.mobile[k] -= divergence(mx, my)
            # Curtis transfer shape, rates per model-time unit. Exact exponential fractions bound stores.
            down = self.mobile[k] * (
                -np.expm1(-dt * pig["rho"] * (1 - self.paper * pig["gamma"]))
            )
            up = (
                self.fixed[k]
                * (
                    -np.expm1(
                        -dt
                        * pig["rho"]
                        / pig["omega"]
                        * (1 + (self.paper - 1) * pig["gamma"])
                    )
                )
                * (self.water > 1e-5)
            )
            dry = self.water < 1e-6
            down = np.where(dry, self.mobile[k], down)
            self.mobile[k] += up - down
            self.fixed[k] += down - up
        for a in [self.water, self.saturation, self.mobile, self.fixed]:
            if not np.isfinite(a).all() or a.min() < -1e-10:
                raise FloatingPointError("Invalid state")
            self.roundoff_correction += float(-a[a < 0].sum() * dx**2)
            a[a < 0] = 0
        self.time += dt

    def report(self):
        total = (self.mobile + self.fixed).sum(axis=(1, 2)) * self.dx**2
        accounted = (
            self.water.sum() + self.saturation.sum()
        ) * self.dx**2 + self.evaporated
        return dict(
            time=self.time,
            parameters=asdict(self.p),
            water_input=self.input_water,
            water_accounted=accounted,
            water_error=accounted - self.input_water,
            pigment_input=self.input_pigment.tolist(),
            pigment_total=total.tolist(),
            pigment_error=(total - self.input_pigment).tolist(),
            min_water=float(self.water.min()),
            min_pigment=float(min(self.mobile.min(), self.fixed.min())),
            roundoff_correction=self.roundoff_correction,
            max_flux_limited_fraction=self.max_flux_limited_fraction,
            wet_cells=int(self.wet.sum()),
        )

    def save(self, path):
        np.savez_compressed(
            path,
            water=self.water,
            saturation=self.saturation,
            mobile=self.mobile,
            fixed=self.fixed,
            paper=self.paper,
            capacity=self.capacity,
            permeability=self.permeability,
            u=self.u,
            v=self.v,
            wet=self.wet,
            time=self.time,
        )


def km_layer(masses, pigments=PIGMENTS):
    """Curtis §5.2 KM reflectance/transmittance; stable exponential form."""
    K = np.einsum("kij,kc->ijc", masses, np.array([p["K"] for p in pigments]))
    S = np.einsum("kij,kc->ijc", masses, np.array([p["S"] for p in pigments]))
    b = np.sqrt(K * (K + 2 * S))
    e = np.exp(-2 * b)
    denom = (K + S) * (1 - e) + b * (1 + e)
    reflect = np.divide(S * (1 - e), denom, out=S / (1 + S), where=denom > 1e-20)
    transmit = np.divide(
        2 * b * np.exp(-b), denom, out=1 / (1 + S), where=denom > 1e-20
    )
    return reflect, transmit


def render(wash, background=(0.94, 0.91, 0.84)):
    r, t = km_layer(wash.mobile + wash.fixed, wash.pigments)
    bg = np.broadcast_to(background, r.shape)
    return np.clip(r + t * t * bg / (1 - r * bg), 0, 1)
