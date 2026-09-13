"""Surface subdivision and a private UV atlas; no external assets."""

import math
import numpy as np


def refine(vertices, triangles, uvs, target):
    vertices = np.asarray(vertices, float)
    triangles = np.asarray(triangles, np.int32)
    uvs = np.asarray(uvs, float)
    while (
        len(vertices) < target and len(vertices) + len(triangles) * 1.5 <= target * 1.6
    ):
        edges = np.sort(
            np.concatenate(
                [triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]
            ),
            axis=1,
        )
        unique, inverse = np.unique(edges, axis=0, return_inverse=True)
        n = len(triangles)
        ab, bc, ca = inverse.reshape(3, n) + len(vertices)
        vertices = np.concatenate([vertices, vertices[unique].mean(axis=1)])
        a, b, c = triangles.T
        ua, ub, uc = uvs[:, 0], uvs[:, 1], uvs[:, 2]
        uab = (ua + ub) / 2
        ubc = (ub + uc) / 2
        uca = (uc + ua) / 2
        triangles = np.concatenate(
            [
                np.stack([a, ab, ca], 1),
                np.stack([ab, b, bc], 1),
                np.stack([ca, bc, c], 1),
                np.stack([ab, bc, ca], 1),
            ]
        )
        uvs = np.concatenate(
            [
                np.stack([ua, uab, uca], 1),
                np.stack([uab, ub, ubc], 1),
                np.stack([uca, ubc, uc], 1),
                np.stack([uab, ubc, uca], 1),
            ]
        )
    return vertices, triangles, uvs


class Atlas:
    def __init__(self, triangles, uvs, size):
        self.size = size
        self.ids = np.zeros((size * size, 3), np.int32)
        self.weights = np.zeros((size * size, 3), np.float32)
        self.valid = np.zeros(size * size, bool)
        for tri, uv in zip(triangles, uvs):
            xy = uv * size - 0.5
            lo = np.maximum(np.floor(xy.min(0)).astype(int), 0)
            hi = np.minimum(np.ceil(xy.max(0)).astype(int) + 1, size)
            if np.any(hi <= lo):
                continue
            yy, xx = np.mgrid[lo[1] : hi[1], lo[0] : hi[0]]
            points = np.stack([xx.ravel(), yy.ravel()], 1)
            basis = np.stack([xy[1] - xy[0], xy[2] - xy[0]], 1)
            if abs(np.linalg.det(basis)) < 1e-12:
                continue
            bc = (points - xy[0]) @ np.linalg.inv(basis).T
            bary = np.column_stack([1 - bc.sum(1), bc])
            valid = (bary >= -1e-5).all(1)
            pix = points[valid, 1] * size + points[valid, 0]
            self.ids[pix] = tri
            self.weights[pix] = bary[valid]
            self.valid[pix] = True
        # Two texels of nearest valid values protect UV islands from filtering seams.
        for _ in range(2):
            good = self.valid.reshape(size, size).copy()
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                target = np.flatnonzero((~good) & np.roll(good, (dy, dx), (0, 1)))
                y, x = np.divmod(target, size)
                inside = (
                    (y - dy >= 0) & (y - dy < size) & (x - dx >= 0) & (x - dx < size)
                )
                target = target[inside]
                source = target - dy * size - dx
                self.ids[target] = self.ids[source]
                self.weights[target] = self.weights[source]
                self.valid[target] = True
        self.pixels = np.ones((size * size, 4), np.float32)

    def pixels_for(self, colors):
        colors = np.asarray(colors, dtype=np.float32)
        self.pixels[:, :3] = np.einsum(
            "ij,ijk->ik", self.weights, colors[self.ids], optimize=True
        )
        self.pixels[~self.valid, :3] = [0.92, 0.88, 0.78]
        return self.pixels.ravel()


def make_uvs(face_count, size):
    side = math.ceil(math.sqrt(face_count))
    cell = 1 / side
    gap = 2.5 / size
    if cell * size < 7:
        raise ValueError(
            "Too many source faces for this texture size; use a coarser mesh or larger atlas"
        )
    out = []
    for n in range(face_count):
        x = (n % side) * cell
        y = (n // side) * cell
        out.append(
            [[x + gap, y + gap], [x + cell - gap, y + gap], [x + gap, y + cell - gap]]
        )
    return np.array(out)
