"""Conservative porous-surface model on barycentric dual cells.

Empirical Darcy-like flow, not a Navier–Stokes solver. Geometry is normalized
by its bounding-box diagonal. Each vertex owns one third of incident face area.
"""

from dataclasses import dataclass, asdict
import heapq
import io
import json
import numpy as np
from .planar import km_layer

PIGMENTS = [
    dict(name="Rose", K=[0.22, 1.47, 0.57], S=[0.05, 0.003, 0.03]),
    dict(name="Blue", K=[1.52, 0.32, 0.25], S=[0.06, 0.26, 0.40]),
    dict(name="Ochre", K=[0.12, 0.42, 1.6], S=[0.45, 0.32, 0.12]),
]


@dataclass
class Settings:
    flow: float = 0.003
    gravity: float = 0.1
    absorption: float = 0.3
    evaporation: float = 0.25
    capacity: float = 0.35
    deposit: float = 2.0
    release: float = 0.6
    capillary: float = 0.0006
    granulation: float = 0.65
    seed: int = 22


class Surface:
    def __init__(self, vertices, triangles):
        self.vertices = np.asarray(vertices, dtype=np.float64)
        self.triangles = np.asarray(triangles, dtype=np.int32)
        v, t = self.vertices, self.triangles
        if v.ndim != 2 or v.shape[1] != 3 or not np.isfinite(v).all():
            raise ValueError("Expected finite 3D vertices")
        if (
            t.ndim != 2
            or t.shape[1] != 3
            or not len(t)
            or t.min() < 0
            or t.max() >= len(v)
        ):
            raise ValueError("Expected valid triangle indices")
        self.scale = float(np.linalg.norm(np.ptp(v, axis=0)))
        if self.scale <= 1e-12:
            raise ValueError("Surface has no extent")
        self.xyz = (v - v.min(axis=0)) / self.scale
        a, b, c = self.xyz[t[:, 0]], self.xyz[t[:, 1]], self.xyz[t[:, 2]]
        face_area = np.linalg.norm(np.cross(b - a, c - a), axis=1) * 0.5
        if np.any(face_area < 1e-15):
            raise ValueError("Remove degenerate faces before preparing")
        self.area = np.bincount(
            t.ravel(), weights=np.repeat(face_area / 3, 3), minlength=len(v)
        )
        if np.any(self.area <= 0):
            raise ValueError("Remove loose vertices before preparing")
        edges = np.sort(
            np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1
        )
        self.edges, counts = np.unique(edges, axis=0, return_counts=True)
        if np.any(counts > 2):
            raise ValueError("Nonmanifold edge: split or repair the surface")
        self.i, self.j = self.edges.T
        self.length = np.linalg.norm(self.xyz[self.j] - self.xyz[self.i], axis=1)
        self.conductance = (self.area[self.i] + self.area[self.j]) / (
            3 * self.length**2
        )
        self.degree = np.bincount(
            self.edges.ravel(), weights=np.repeat(self.conductance, 2), minlength=len(v)
        )
        self.neighbors = [[] for _ in v]
        for i, j, d in zip(self.i, self.j, self.length):
            self.neighbors[i].append((int(j), float(d)))
            self.neighbors[j].append((int(i), float(d)))

    def footprint(self, triangle, point, radius):
        """Truncated graph geodesic; cannot jump across disconnected surfaces."""
        radius = float(radius) / self.scale
        if radius <= 0:
            raise ValueError("Brush radius must be positive")
        p = (np.asarray(point) - self.vertices.min(axis=0)) / self.scale
        seeds = self.triangles[int(triangle)]
        distances = {int(i): float(np.linalg.norm(self.xyz[i] - p)) for i in seeds}
        queue = [(d, i) for i, d in distances.items()]
        heapq.heapify(queue)
        while queue:
            d, i = heapq.heappop(queue)
            if d > distances[i] or d > radius:
                continue
            for j, edge in self.neighbors[i]:
                nd = d + edge
                if nd < radius and nd < distances.get(j, float("inf")):
                    distances[j] = nd
                    heapq.heappush(queue, (nd, j))
        ids = np.array([i for i, d in distances.items() if d < radius], dtype=np.int32)
        if not len(ids):
            i = min(distances, key=distances.get)
            return np.array([i]), np.array([1.0])
        d = np.array([distances[int(i)] for i in ids]) / radius
        return ids, (1 - d * d) ** 2


class Paint:
    def __init__(self, surface, settings=None):
        self.surface = surface
        self.settings = settings or Settings()
        n = len(surface.vertices)
        # Seeded spatial substrate, independent of vertex ordering.
        x = surface.xyz
        rng = np.random.default_rng(self.settings.seed)
        self.paper = np.zeros(n)
        for _ in range(12):
            k = rng.normal(size=3) * rng.uniform(30, 180)
            self.paper += np.sin(x @ k + rng.uniform(0, 6.28)) / 12
        self.paper = np.clip(0.5 + self.paper, 0, 1)
        self.water = np.zeros(n)
        self.absorbed = np.zeros(n)
        self.mobile = np.zeros((3, n))
        self.fixed = np.zeros((3, n))
        self.base = np.broadcast_to(np.array([0.92, 0.88, 0.78]), (n, 3)).copy()
        self.time = 0.0
        self.water_input = 0.0
        self.evaporated = 0.0
        self.water_removed = 0.0
        self.pigment_input = np.zeros(3)
        self.pigment_removed = np.zeros(3)

    def apply(self, ids, weights, mode="PIGMENT", pigment=0, water=0.3, load=0.4):
        ids = np.asarray(ids, dtype=np.int32)
        weights = np.clip(np.asarray(weights), 0, 1)
        if (
            not np.isfinite(weights).all()
            or water < 0
            or load < 0
            or not np.isfinite([water, load]).all()
        ):
            raise ValueError("Brush loads must be finite and nonnegative")
        area = self.surface.area[ids]
        if mode == "LIFT":
            fraction = 1 - np.exp(-weights * load * 4)
            removed = (
                self.mobile[:, ids] * fraction + self.fixed[:, ids] * fraction * 0.35
            )
            self.mobile[:, ids] *= 1 - fraction
            self.fixed[:, ids] *= 1 - fraction * 0.35
            self.pigment_removed += (removed * area).sum(axis=1)
            wr = self.water[ids] * fraction
            self.water[ids] -= wr
            self.water_removed += float(wr @ area)
            return
        amount = weights * water
        self.water[ids] += amount
        self.water_input += float(amount @ area)
        if mode == "PIGMENT":
            mass = weights * load
            self.mobile[pigment, ids] += mass
            self.pigment_input[pigment] += float(mass @ area)

    def _exchange(self, field, flux, receiver_capacity=None):
        """Flux is mass across each edge; bounded donors, paired update."""
        s = self.surface
        i, j = s.i, s.j
        donor = np.where(flux >= 0, i, j)
        receiver = np.where(flux >= 0, j, i)
        amount = abs(flux)
        available = np.maximum(field * s.area, 0)
        outgoing = np.bincount(donor, weights=amount, minlength=len(field))
        amount *= np.minimum(1, available / np.maximum(outgoing, 1e-30))[donor]
        if receiver_capacity is not None:
            incoming = np.bincount(receiver, weights=amount, minlength=len(field))
            amount *= np.minimum(
                1,
                np.maximum(receiver_capacity - field, 0)
                * s.area
                / np.maximum(incoming, 1e-30),
            )[receiver]
        delta = np.bincount(
            receiver, weights=amount, minlength=len(field)
        ) - np.bincount(donor, weights=amount, minlength=len(field))
        field += delta / s.area
        return donor, receiver, amount

    def stable_dt(self):
        p = self.settings
        s = self.surface
        return min(
            0.03,
            float(np.min(s.area / np.maximum(s.degree, 1e-20)))
            * 0.22
            / max(p.flow, p.capillary, 1e-9),
        )

    def step(self, dt=None):
        p = self.settings
        s = self.surface
        i, j = s.i, s.j
        dt = self.stable_dt() if dt is None else float(dt)
        if not np.isfinite(dt) or dt <= 0 or dt > self.stable_dt() * 1.000001:
            raise ValueError("Unstable timestep")
        capacity = p.capacity * (0.7 + 0.6 * self.paper)
        # Pressure is water depth plus gravitational elevation along the surface.
        head = self.water + p.gravity * s.xyz[:, 2]
        wet = np.maximum(self.water[i], self.water[j]) > 1e-8
        flux = dt * p.flow * s.conductance * (head[i] - head[j]) * wet
        before = self.water.copy()
        donor, receiver, moved = self._exchange(self.water, flux)
        for k in range(3):
            concentration = np.divide(
                self.mobile[k], before, out=np.zeros_like(before), where=before > 1e-12
            )
            pigment = moved * concentration[donor]
            # Same conservative water transfers, with bounded pigment availability.
            sign = np.where(flux >= 0, 1.0, -1.0)
            self._exchange(self.mobile[k], sign * pigment)
        self._exchange(
            self.absorbed,
            dt * p.capillary * s.conductance * (self.absorbed[i] - self.absorbed[j]),
            capacity,
        )
        take = np.minimum(
            self.water,
            np.minimum(
                dt * p.absorption * (0.6 + self.paper),
                np.maximum(capacity - self.absorbed, 0),
            ),
        )
        self.water -= take
        self.absorbed += take
        # Backflow from saturated substrate supplies a spreading wet front.
        release = np.minimum(
            self.absorbed, np.maximum(self.absorbed - capacity * 0.85, 0) * dt * 0.4
        )
        self.absorbed -= release
        self.water += release
        # Enhanced evaporation at a wet/dry boundary drives transport toward it.
        dry_neighbors = np.bincount(
            np.concatenate([i, j]),
            weights=np.concatenate([self.water[j] < 1e-5, self.water[i] < 1e-5]),
            minlength=len(self.water),
        )
        wet_edge = (dry_neighbors > 0) & (self.water > 1e-5)
        ev = np.minimum(self.water, dt * p.evaporation * (1 + 0.8 * wet_edge))
        ea = np.minimum(self.absorbed, dt * p.evaporation * 0.3)
        self.water -= ev
        self.absorbed -= ea
        self.evaporated += float((ev + ea) @ s.area)
        grain = 1 + p.granulation * (1 - self.paper) * 2
        down = self.mobile * (1 - np.exp(-dt * p.deposit * grain))
        up = self.fixed * (1 - np.exp(-dt * p.release)) * (self.water > 1e-4)
        down = np.where(self.water < 1e-6, self.mobile, down)
        self.mobile += up - down
        self.fixed += down - up
        for f in (self.water, self.absorbed, self.mobile, self.fixed):
            if not np.isfinite(f).all() or f.min() < -1e-10:
                raise FloatingPointError("Invalid simulation state")
            np.maximum(f, 0, out=f)
        self.time += dt

    def colors(self):
        masses = (self.mobile + self.fixed)[:, :, None]
        r, t = km_layer(masses, PIGMENTS)
        r = r[:, 0]
        t = t[:, 0]
        return np.clip(r + t * t * self.base / (1 - r * self.base), 0, 1)

    def bake(self):
        self.base = self.colors()
        self.water.fill(0)
        self.absorbed.fill(0)
        self.mobile.fill(0)
        self.fixed.fill(0)
        self.water_input = self.evaporated = self.water_removed = 0.0
        self.pigment_input.fill(0)
        self.pigment_removed.fill(0)

    def report(self):
        area = self.surface.area
        return dict(
            time=self.time,
            water_error=float(
                (self.water + self.absorbed) @ area
                + self.evaporated
                + self.water_removed
                - self.water_input
            ),
            pigment_error=(
                (self.mobile + self.fixed) @ area
                + self.pigment_removed
                - self.pigment_input
            ).tolist(),
            min_water=float(self.water.min()),
            min_pigment=float(min(self.mobile.min(), self.fixed.min())),
        )

    def dumps(self, compress=True):
        meta = dict(
            settings=asdict(self.settings),
            time=self.time,
            water_input=self.water_input,
            evaporated=self.evaporated,
            water_removed=self.water_removed,
        )
        out = io.BytesIO()
        writer = np.savez_compressed if compress else np.savez
        writer(
            out,
            vertices=self.surface.vertices,
            triangles=self.surface.triangles,
            water=self.water,
            absorbed=self.absorbed,
            mobile=self.mobile,
            fixed=self.fixed,
            paper=self.paper,
            base=self.base,
            pigment_input=self.pigment_input,
            pigment_removed=self.pigment_removed,
            meta=json.dumps(meta),
        )
        return out.getvalue()

    @classmethod
    def loads(cls, data):
        with np.load(io.BytesIO(data), allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            state = cls(
                Surface(z["vertices"], z["triangles"]), Settings(**meta.pop("settings"))
            )
            for key in (
                "water",
                "absorbed",
                "mobile",
                "fixed",
                "paper",
                "base",
                "pigment_input",
                "pigment_removed",
            ):
                setattr(state, key, z[key].copy())
            for key, value in meta.items():
                setattr(state, key, value)
        return state
