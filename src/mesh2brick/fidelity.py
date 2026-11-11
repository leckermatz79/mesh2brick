# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Shape fidelity: how far the surface of a brick model lies from the input mesh.

The metric of the 2.0 series (ROADMAP "shape fidelity"): every item there
(tiles, more slopes, curved parts, SNOT) should bring the outside of the
built model closer to the mesh it was made from, at unchanged stability.

How it is measured (all in real LEGO millimetres, 8 mm per stud, 3.2 mm per
plate, so models of every size compare):

1. **Brick surface.** The outside of the model only: cell faces between a
   part and the air around the model (cavities of hollow models do not
   count). Studs count with their real size (4.8 mm wide, 1.7 mm high); tiles
   and the sloped columns of slopes have none, and slopes are sampled on their
   sloped face, as the preview draws them.
2. **Samples.** Every face is sampled on a regular grid (about one point per
   :data:`SAMPLE_SPACING_MM` in each direction), each point weighted with the
   area it stands for, so a big face weighs more than a small one.
3. **Distance.** For every sample the exact distance to the nearest triangle
   of the input mesh (unsigned). Reported: the area-weighted mean and 95th
   percentile, in mm and in studs.

The metric is one-sided (brick surface to mesh): it says how far the parts
stick out or fall short where there are parts, not whether thin details of the
mesh are missing. Pure functions, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree

from mesh2brick.model import MM_PER_PLATE, MM_PER_STUD, STUD_HEIGHT_MM
from mesh2brick.render.preview import slope_faces
from mesh2brick.voxel.grid import LEGO_MM_PER_STUD

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from mesh2brick.model import BrickModel
    from mesh2brick.render.preview import SlopeFace
    from mesh2brick.voxel.grid import VoxelGrid

SAMPLE_SPACING_MM: Final = 2.0
"""Distance between surface samples: 16 per stud top, 8 per plate side."""
STUD_RADIUS_MM: Final = 2.4
"""Half the 4.8 mm stud diameter."""
PERCENTILE: Final = 95.0
MAX_EDGE_MM: Final = 4.0
"""Mesh triangles are split until no edge is longer (bounds the search)."""
NEAREST: Final = 16
"""Candidate triangles per sample before the exact search widens."""
_BATCH: Final = 20_000
_STUD_TOP_RING: Final = 6
_STUD_SIDE_POINTS: Final = 8
_EPS: Final = 1e-12
_SCALE: Final = np.array([MM_PER_STUD, MM_PER_STUD, MM_PER_PLATE])
_FACES: Final = ndimage.generate_binary_structure(3, 1)
_DIRECTIONS: Final = (
    (0, 0, 1),
    (0, 0, -1),
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
)


@dataclass(frozen=True, slots=True)
class SurfaceDeviation:
    """Distance of a brick model's surface to the input mesh.

    Attributes:
        mean_mm: area-weighted mean distance in LEGO millimetres.
        p95_mm: 95 % of the surface lies at most this far from the mesh.
        area_mm2: sampled outer surface of the brick model.
        samples: number of sample points.
    """

    mean_mm: float
    p95_mm: float
    area_mm2: float
    samples: int

    @property
    def mean_studs(self) -> float:
        """:attr:`mean_mm` in studs (8 mm)."""
        return self.mean_mm / MM_PER_STUD

    @property
    def p95_studs(self) -> float:
        """:attr:`p95_mm` in studs (8 mm)."""
        return self.p95_mm / MM_PER_STUD

    def as_dict(self) -> dict[str, float | int]:
        """Rounded numbers for benchmark files."""
        return {
            "mean_mm": round(self.mean_mm, 3),
            "p95_mm": round(self.p95_mm, 3),
            "mean_studs": round(self.mean_studs, 4),
            "p95_studs": round(self.p95_studs, 4),
            "area_mm2": round(self.area_mm2, 1),
            "samples": self.samples,
        }


# --------------------------------------------------------------------------- API
def surface_deviation(
    model: BrickModel,
    vertices: NDArray[np.float64],
    faces: NDArray[np.int64],
) -> SurfaceDeviation:
    """Distance of ``model``'s outer surface to a mesh in the model's frame.

    ``vertices``/``faces`` describe the input mesh in LEGO millimetres of the
    brick model's grid (see :func:`lego_frame`).

    Raises:
        ValueError: for an empty model or mesh.
    """
    points, weights = surface_samples(model)
    distances = point_mesh_distances(points, vertices, faces)
    total = float(weights.sum())
    mean = float((distances * weights).sum() / total)
    return SurfaceDeviation(
        mean_mm=mean,
        p95_mm=weighted_percentile(distances, weights, PERCENTILE),
        area_mm2=total,
        samples=len(points),
    )


def lego_frame(
    vertices: NDArray[np.float64],
    origin_mm: tuple[float, float, float],
    pitch_mm: float,
) -> NDArray[np.float64]:
    """Mesh vertices (model mm) -> LEGO mm of the grid built from them.

    The voxel grid's cell ``(0, 0, 0)`` starts at ``origin_mm`` and one stud
    is ``pitch_mm`` model millimetres; LEGO has 8 mm per stud and the same
    proportions vertically, so the scale is uniform.
    """
    scale = LEGO_MM_PER_STUD / pitch_mm
    shifted: NDArray[np.float64] = (
        np.asarray(vertices, dtype=np.float64) - np.asarray(origin_mm)
    ) * scale
    return shifted


def grid_mesh(grid: VoxelGrid) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """The outer faces of a voxel grid as triangles in model millimetres.

    The reference surface for inputs that are voxels already (``.vox``): there
    the cells are the design.
    """
    padded = np.pad(grid.occupancy, 1)
    dx, dy, dz = grid.cell_size_mm
    quads: list[NDArray[np.float64]] = []
    for direction in _DIRECTIONS:
        d = np.asarray(direction)
        exposed = padded & ~np.roll(padded, shift=-d, axis=(0, 1, 2))
        at = np.argwhere(exposed) - 1
        if len(at):
            quads.append(_box_face_corners(at.astype(np.float64), d))
    corners = np.concatenate(quads) * np.array([dx, dy, dz]) + np.asarray(
        grid.origin_mm
    )
    vertices = corners.reshape(-1, 3)
    base = np.arange(len(corners))[:, None] * 4
    first, second = np.asarray([0, 1, 2]), np.asarray([0, 2, 3])
    faces = np.concatenate([base + first, base + second]).astype(np.int64)
    return vertices, faces


# --------------------------------------------------------------------------- samples
def surface_samples(
    model: BrickModel, spacing_mm: float = SAMPLE_SPACING_MM
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Points on the outer surface of ``model`` (LEGO mm) and their areas (mm²).

    Raises:
        ValueError: for a model without parts.
    """
    if not model.parts:
        msg = "an empty model has no surface"
        raise ValueError(msg)
    cells = np.asarray([c for p in model.parts for c in p.cells], dtype=np.int64)
    owner_of = np.repeat(
        np.arange(model.part_count), [len(p.cells) for p in model.parts]
    )
    low = cells.min(axis=0) - 1
    shape = tuple(int(n) for n in cells.max(axis=0) - low + 2)
    local = cells - low
    occupied = np.zeros(shape, dtype=bool)
    occupied[local[:, 0], local[:, 1], local[:, 2]] = True
    outside = _outside_air(occupied)
    studded = np.zeros(shape, dtype=bool)
    sloped = np.zeros(shape, dtype=bool)
    wedges: list[list[SlopeFace]] = []
    for index, part in enumerate(model.parts):
        tops = part.top_studs
        if tops:
            mine = local[owner_of == index]
            flags = np.asarray([(x, y) in tops for x, y, _ in part.cells])
            studded[mine[flags, 0], mine[flags, 1], mine[flags, 2]] = True
        wedge = slope_faces(part)
        if wedge is not None:
            at = np.asarray(sorted(wedge[0]), dtype=np.int64) - low
            sloped[at[:, 0], at[:, 1], at[:, 2]] = True
            wedges.append(wedge[1])

    points: list[NDArray[np.float64]] = []
    weights: list[NDArray[np.float64]] = []
    for direction in _DIRECTIONS:
        d = np.asarray(direction)
        exposed = (
            occupied
            & ~sloped
            & np.roll(outside, shift=-d, axis=(0, 1, 2))  # neighbour is outside
        )
        at = np.argwhere(exposed)
        if not len(at):
            continue
        world = (at + low).astype(np.float64)
        if direction == (0, 0, 1):
            with_stud = studded[at[:, 0], at[:, 1], at[:, 2]]
            for chosen, stud in ((~with_stud, False), (with_stud, True)):
                if chosen.any():
                    p, w = _top_samples(world[chosen], spacing_mm, stud=stud)
                    points.append(p)
                    weights.append(w)
            continue
        p, w = _face_samples(_box_face_corners(world, d) * _SCALE, spacing_mm)
        points.append(p)
        weights.append(w)

    for faces in wedges:
        for face in faces:
            if not _wedge_face_exposed(face, outside, low):
                continue
            p, w = _face_samples(face.corners[None] * _SCALE, spacing_mm)
            points.append(p)
            weights.append(w)
    return np.concatenate(points), np.concatenate(weights)


def _outside_air(occupied: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Empty cells connected to the border (the border cells are all empty)."""
    labels, _ = ndimage.label(~occupied, structure=_FACES)
    outside: NDArray[np.bool_] = labels == labels[0, 0, 0]
    return outside


def _wedge_face_exposed(
    face: SlopeFace, outside: NDArray[np.bool_], low: NDArray[np.int64]
) -> bool:
    """Sloped tops always count; sides, lip and bottom where air is next to them."""
    if face.outward[2] > 0:
        return True
    centre = face.corners.mean(axis=0) + 0.5 * np.asarray(face.outward)
    cell = np.floor(centre).astype(np.int64) - low
    if np.any(cell < 0) or np.any(cell >= outside.shape):
        return True
    return bool(outside[cell[0], cell[1], cell[2]])


def _box_face_corners(
    cells: NDArray[np.float64], direction: NDArray[np.int64]
) -> NDArray[np.float64]:
    """``(n, 4, 3)`` corners of the faces of unit cells facing ``direction``."""
    axis = int(np.flatnonzero(direction)[0])
    a, b = [k for k in range(3) if k != axis]
    corners = np.zeros((len(cells), 4, 3))
    offsets = ((0, 0), (1, 0), (1, 1), (0, 1))
    for i, (da, db) in enumerate(offsets):
        corner = cells.copy()
        corner[:, axis] += 1.0 if direction[axis] > 0 else 0.0
        corner[:, a] += da
        corner[:, b] += db
        corners[:, i] = corner
    return corners


def _face_samples(
    quads: NDArray[np.float64], spacing_mm: float
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Regular samples on planar quads ``(n, 4, 3)`` (mm), weighted by area.

    All quads of one call have the same shape (one direction of box faces or
    one slope face), so they share one grid of parameters.
    """
    first = quads[0]
    side_a = float(np.linalg.norm(first[1] - first[0]))
    side_b = float(np.linalg.norm(first[3] - first[0]))
    na = max(1, round(side_a / spacing_mm))
    nb = max(1, round(side_b / spacing_mm))
    s = (np.arange(na) + 0.5) / na
    t = (np.arange(nb) + 0.5) / nb
    ss, tt = (g.ravel() for g in np.meshgrid(s, t, indexing="ij"))
    c0, c1, c2, c3 = (quads[:, i, None, :] for i in range(4))
    w0 = ((1 - ss) * (1 - tt))[None, :, None]
    w1 = (ss * (1 - tt))[None, :, None]
    w2 = (ss * tt)[None, :, None]
    w3 = ((1 - ss) * tt)[None, :, None]
    points = c0 * w0 + c1 * w1 + c2 * w2 + c3 * w3
    area = 0.5 * np.linalg.norm(
        np.cross(quads[:, 2] - quads[:, 0], quads[:, 3] - quads[:, 1]), axis=1
    )
    weights = np.repeat(area / (na * nb), na * nb)
    return points.reshape(-1, 3), weights


def _top_samples(
    cells: NDArray[np.float64], spacing_mm: float, *, stud: bool
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Samples on open cell tops (mm); with ``stud`` around and on a stud."""
    n = max(1, round(MM_PER_STUD / spacing_mm))
    grid = (np.arange(n) + 0.5) / n * MM_PER_STUD
    gx, gy = (g.ravel() for g in np.meshgrid(grid, grid, indexing="ij"))
    flat = np.stack([gx, gy, np.zeros_like(gx)], axis=1)
    top_area = MM_PER_STUD * MM_PER_STUD
    if not stud:
        offsets = flat
        weights = np.full(len(flat), top_area / len(flat))
    else:
        centre = np.array([MM_PER_STUD / 2, MM_PER_STUD / 2, 0.0])
        ring = np.hypot(gx - centre[0], gy - centre[1]) >= STUD_RADIUS_MM
        disc = np.pi * STUD_RADIUS_MM**2
        angles = np.arange(_STUD_TOP_RING) / _STUD_TOP_RING * 2 * np.pi
        top = np.concatenate(
            [
                [[0.0, 0.0]],
                np.stack([np.cos(angles), np.sin(angles)], axis=1)
                * (STUD_RADIUS_MM * 2 / 3),
            ]
        )
        stud_top = np.column_stack([top, np.full(len(top), STUD_HEIGHT_MM)])
        stud_top[:, :2] += centre[:2]
        around = np.arange(_STUD_SIDE_POINTS) / _STUD_SIDE_POINTS * 2 * np.pi
        side = np.stack(
            [
                centre[0] + STUD_RADIUS_MM * np.cos(around),
                centre[1] + STUD_RADIUS_MM * np.sin(around),
                np.full(_STUD_SIDE_POINTS, STUD_HEIGHT_MM / 2),
            ],
            axis=1,
        )
        side_area = 2 * np.pi * STUD_RADIUS_MM * STUD_HEIGHT_MM
        offsets = np.concatenate([flat[ring], stud_top, side])
        weights = np.concatenate(
            [
                np.full(int(ring.sum()), (top_area - disc) / int(ring.sum())),
                np.full(len(stud_top), disc / len(stud_top)),
                np.full(_STUD_SIDE_POINTS, side_area / _STUD_SIDE_POINTS),
            ]
        )
    base = (cells + np.asarray([0.0, 0.0, 1.0])) * _SCALE
    points = base[:, None, :] + offsets[None, :, :]
    return points.reshape(-1, 3), np.tile(weights, len(cells))


# --------------------------------------------------------------------------- distance
def point_mesh_distances(
    points: NDArray[np.float64],
    vertices: NDArray[np.float64],
    faces: NDArray[np.int64],
) -> NDArray[np.float64]:
    """Exact distance from every point to the nearest triangle of a mesh.

    Triangles are split until no edge exceeds :data:`MAX_EDGE_MM`; a k-d tree
    of their centroids gives :data:`NEAREST` candidates per point, and a point
    whose answer could still come from a farther triangle is searched again
    within the provable radius.

    Raises:
        ValueError: for an empty mesh.
    """
    if not len(faces):
        msg = "the mesh has no triangles"
        raise ValueError(msg)
    verts, tris = trimesh.remesh.subdivide_to_size(  # type: ignore[no-untyped-call]
        vertices, faces, max_edge=MAX_EDGE_MM, max_iter=24
    )
    triangles = np.asarray(verts, dtype=np.float64)[np.asarray(tris)]
    centroids = triangles.mean(axis=1)
    reach = float(np.linalg.norm(triangles - centroids[:, None], axis=2).max())
    tree = cKDTree(centroids)
    k = min(NEAREST, len(triangles))
    result = np.empty(len(points))
    for start in range(0, len(points), _BATCH):
        batch = points[start : start + _BATCH]
        gap, nearest = tree.query(batch, k=k)
        gap = gap.reshape(len(batch), k)
        nearest = nearest.reshape(len(batch), k)
        exact = triangle_distances(
            np.repeat(batch, k, axis=0), triangles[nearest.ravel()]
        ).reshape(len(batch), k)
        best = exact.min(axis=1)
        # A triangle beyond the k-th centroid is at least gap[k] - reach away.
        unsure = np.flatnonzero((best > gap[:, -1] - reach) & (k < len(triangles)))
        for i in unsure:
            ids = tree.query_ball_point(batch[i], best[i] + reach)
            if ids:
                many = triangle_distances(
                    np.repeat(batch[i : i + 1], len(ids), axis=0), triangles[ids]
                )
                best[i] = min(best[i], float(many.min()))
        result[start : start + len(batch)] = best
    return result


def triangle_distances(
    points: NDArray[np.float64], triangles: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Distance of ``points[i]`` to triangle ``triangles[i]`` (``(n, 3, 3)``).

    Closest point by Voronoi regions of the triangle (C. Ericson, *Real-Time
    Collision Detection*, 5.1.5), vectorized; degenerate triangles fall back
    to their nearest corner or edge through the same regions.
    """
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    ab, ac = b - a, c - a
    ap, bp, cp = points - a, points - b, points - c
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    with np.errstate(divide="ignore", invalid="ignore"):
        t_ab = np.clip(d1 / (d1 - d3), 0.0, 1.0)
        t_ac = np.clip(d2 / (d2 - d6), 0.0, 1.0)
        t_bc = np.clip((d4 - d3) / ((d4 - d3) + (d5 - d6)), 0.0, 1.0)
        denom = va + vb + vc
        v = vb / denom
        w = vc / denom
    face = a + ab * v[:, None] + ac * w[:, None]
    conditions = [
        (d1 <= 0) & (d2 <= 0),
        (d3 >= 0) & (d4 <= d3),
        (vc <= 0) & (d1 >= 0) & (d3 <= 0),
        (d6 >= 0) & (d5 <= d6),
        (vb <= 0) & (d2 >= 0) & (d6 <= 0),
        (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0),
    ]
    choices = [
        a,
        b,
        a + ab * t_ab[:, None],
        c,
        a + ac * t_ac[:, None],
        b + (c - b) * t_bc[:, None],
    ]
    closest = np.select([cond[:, None] for cond in conditions], choices, default=face)
    distance: NDArray[np.float64] = np.linalg.norm(points - closest, axis=1)
    bad = ~np.isfinite(distance) | (np.abs(denom) < _EPS)
    if bad.any():
        corners = np.linalg.norm(points[bad, None] - triangles[bad], axis=2).min(axis=1)
        distance[bad] = np.minimum(np.nan_to_num(distance[bad], nan=np.inf), corners)
    return distance


def weighted_percentile(
    values: NDArray[np.float64], weights: NDArray[np.float64], percent: float
) -> float:
    """The value below which ``percent`` % of the total weight lies."""
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    index = int(np.searchsorted(cumulative, percent / 100 * cumulative[-1]))
    return float(values[order][min(index, len(values) - 1)])


def _dot(u: NDArray[np.float64], v: NDArray[np.float64]) -> NDArray[np.float64]:
    result: NDArray[np.float64] = np.einsum("ij,ij->i", u, v)
    return result
