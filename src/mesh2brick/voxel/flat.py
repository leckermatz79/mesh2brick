# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Which top faces of a voxel model the input mesh renders flat (ROADMAP 9).

A tile belongs where the model is meant to be smooth: the top of a box, a
base, a flat detail. It does not belong on the stairs that voxels make of a
rounded surface, even where such a stair happens to be level. Only the mesh
knows the difference, so the voxelizer marks those cells while it still has
the mesh (ADR 0020):

1. **Rays.** Every *top cell* (filled, empty above) is looked at through the
   ``S x S`` vertical rays of its footprint, as in voxelization. Each ray takes
   the up-facing mesh surface closest to the cell's top, from the cell's bottom
   up to one cell above its top.
2. **Flat rays.** A ray is flat when that surface tilts at most
   :data:`MAX_TILT_DEG` from horizontal.
3. **Core cells.** Every ray flat and all hits within :data:`TOLERANCE_MM` of
   each other (in real LEGO millimetres): one horizontal face covers the cell.
4. **Faces.** Core cells of one layer that touch side by side form a face;
   faces of fewer than :data:`MIN_FACE_CELLS` cells are dropped (a lone level
   facet on a dome).
5. **Edges.** A top cell next to a face, covered at least half by flat rays at
   that face's height, belongs to it: most faces do not end on a stud line.
6. **Overhang** (optional): a top cell next to a face (corners included)
   whose rays find that face or nothing at all stands out past the mesh
   (rounding, or surface voxelization of an open mesh); with ``overhang`` it
   belongs to the face too, at the face's height.

The result marks the top cells that may get a tile, with the height of the
face above the cell's top (cells; within half a cell, by the fill rule), so
the tile can sit where the face is; everything else keeps its studs. Pure
functions on arrays, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
from scipy import ndimage

from mesh2brick.voxel.rays import JITTER, ray_hits

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from mesh2brick.voxel.voxelize import Lattice

MAX_TILT_DEG: Final = 1.0
"""Steeper faces are not flat (1° rises 0.14 mm over one stud)."""
TOLERANCE_MM: Final = 0.1
"""Height differences on one face up to this (LEGO mm) count as level."""
MIN_FACE_CELLS: Final = 2
"""Smaller level faces are artefacts of curved surfaces, not design."""
EDGE_SHARE: Final = 0.5
"""Share of flat rays a border cell needs to join the face next to it."""
_IN_LAYER: Final = np.zeros((3, 3, 3), dtype=bool)
_IN_LAYER[:, :, 1] = ndimage.generate_binary_structure(2, 1)
_SIDES: Final = ((1, 0), (-1, 0), (0, 1), (0, -1))
_AROUND: Final = (*_SIDES, (1, 1), (1, -1), (-1, 1), (-1, -1))
"""One ring of cells around a face, corners included (the overhang)."""


def top_cells(occupancy: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Filled cells with nothing directly above them in the grid."""
    tops = occupancy.copy()
    tops[:, :, :-1] &= ~occupancy[:, :, 1:]
    return tops


def flat_tops(
    triangles: NDArray[np.float64],
    occupancy: NDArray[np.bool_],
    lattice: Lattice,
    *,
    lego_cell_height_mm: float,
    samples: int = 4,
    overhang: bool = False,
) -> NDArray[np.float32]:
    """How far the flat face over each top cell lies above the cell's top.

    In cell layers (positive: the face is higher than the voxels); ``NaN``
    for cells that are not a flat top.

    Args:
        triangles: ``(m, 3, 3)`` mesh triangles in model mm, outward winding.
        occupancy: the voxel grid on ``lattice``.
        lattice: where the cells sit in model space.
        lego_cell_height_mm: real height of one cell layer (9.6 or 3.2 mm),
            the scale of :data:`TOLERANCE_MM`.
        samples: rays per cell and horizontal axis.
        overhang: also count the top cells next to a face that stand out
            beyond the mesh (every ray finds the face or nothing at all):
            voxels the rounding put one cell past the face's edge (product
            owner, 2026-11-12, "Rand-Fliesen").
    """
    tops = top_cells(occupancy)
    stats = _ray_stats(_closest_hits(triangles, tops, lattice, samples), tops.shape)
    rays, flat, mean = stats.rays, stats.flat, stats.mean
    tolerance = TOLERANCE_MM / lego_cell_height_mm
    level = (stats.high - stats.low) <= tolerance
    core = tops & (flat == rays) & (rays == samples * samples) & level
    labels, _ = ndimage.label(core, structure=_IN_LAYER)
    sizes = np.bincount(labels.ravel())
    face = core & (sizes[labels] >= MIN_FACE_CELLS)
    border = tops & ~face & level & (flat >= EDGE_SHARE * samples * samples)
    edge = np.zeros_like(face)
    beyond = tops & ~face & (flat == rays) & (flat < EDGE_SHARE * samples * samples)
    beyond &= level | (flat == 0)
    height = mean.copy()
    out = np.zeros_like(face)
    for dx, dy in _SIDES:
        neighbour_face = _shifted(face, dx, dy, fill=False)
        neighbour_mean = _shifted(mean, dx, dy, fill=np.inf)
        edge |= border & neighbour_face & (np.abs(neighbour_mean - mean) <= tolerance)
    for dx, dy in _AROUND if overhang else ():
        neighbour_face = _shifted(face | edge, dx, dy, fill=False)
        neighbour_mean = _shifted(mean, dx, dy, fill=np.inf)
        joins = beyond & neighbour_face & ~out
        joins &= (flat == 0) | (np.abs(neighbour_mean - mean) <= tolerance)
        height = np.where(joins & (flat == 0), neighbour_mean, height)
        out |= joins
    top = np.arange(occupancy.shape[2]) + 1.0
    offset: NDArray[np.float32] = np.where(
        face | edge | out, height - top[None, None, :], np.nan
    ).astype(np.float32)
    return offset


@dataclass(frozen=True, slots=True)
class _Hits:
    """The closest up-facing surface of every ray of every top cell.

    ``cell`` is the flat index of the top cell, ``height`` in cell layers.
    """

    cell: NDArray[np.int64]
    height: NDArray[np.float64]
    flat: NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class _RayStats:
    """Per cell: rays that found a surface, flat rays, heights of flat hits.

    Heights are in cell layers; cells without flat rays have ``low = +inf``,
    ``high = -inf`` and ``mean = nan``.
    """

    rays: NDArray[np.int64]
    flat: NDArray[np.int64]
    low: NDArray[np.float64]
    high: NDArray[np.float64]
    mean: NDArray[np.float64]


def _closest_hits(
    triangles: NDArray[np.float64],
    tops: NDArray[np.bool_],
    lattice: Lattice,
    samples: int,
) -> _Hits:
    """Per ray of a top cell, the up-facing surface closest to the cell's top.

    A surface at height ``h`` (cell layers) can be the top of cell
    ``floor(h) - 1`` or ``floor(h)``: the window runs from the cell's bottom
    to one cell above its top.
    """
    nx, ny, nz = tops.shape
    empty = _Hits(np.zeros(0, np.int64), np.zeros(0), np.zeros(0, dtype=bool))
    if not tops.any() or not len(triangles):
        return empty
    step = lattice.pitch / samples
    ox, oy, oz = lattice.origin
    u = (triangles[:, :, 0] - ox) / step - 0.5 - JITTER[0]
    v = (triangles[:, :, 1] - oy) / step - 0.5 - JITTER[1]
    w = (triangles[:, :, 2] - oz) / lattice.cell_height
    normal = np.cross(
        triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    )
    length = np.linalg.norm(normal, axis=1)
    level = np.abs(normal[:, 2]) >= math.cos(math.radians(MAX_TILT_DEG)) * length

    per_cell = samples * samples
    keys: list[NDArray[np.int64]] = []
    scores: list[NDArray[np.float64]] = []
    heights: list[NDArray[np.float64]] = []
    flats: list[NDArray[np.bool_]] = []
    for hits in ray_hits(u, v, nx * samples, ny * samples):
        up = hits.sign < 0  # the rays point up: they leave through up-facing faces
        tri = hits.triangle[up]
        h = np.einsum("ij,ij->i", hits.bary[up], w[tri])
        x, sub_x = np.divmod(hits.ray_i[up], samples)
        y, sub_y = np.divmod(hits.ray_j[up], samples)
        for offset in (1, 0):
            z = np.floor(h).astype(np.int64) - offset
            ok = (z >= 0) & (z < nz)
            ok[ok] = tops[x[ok], y[ok], z[ok]]
            cell = (x[ok] * ny + y[ok]) * nz + z[ok]
            keys.append(cell * per_cell + sub_x[ok] * samples + sub_y[ok])
            scores.append(np.abs(h[ok] - (z[ok] + 1)))
            heights.append(h[ok])
            flats.append(level[tri[ok]])
    key = np.concatenate(keys) if keys else np.zeros(0, np.int64)
    if not key.size:  # no up-facing surface near any top (an open mesh)
        return empty
    order = np.lexsort((np.concatenate(scores), key))
    key = key[order]
    first = np.r_[True, key[1:] != key[:-1]]
    return _Hits(
        cell=key[first] // per_cell,
        height=np.concatenate(heights)[order][first],
        flat=np.concatenate(flats)[order][first],
    )


def _ray_stats(hits: _Hits, shape: tuple[int, ...]) -> _RayStats:
    """Count and summarise the hits per cell."""
    rays = np.zeros(shape, dtype=np.int64)
    flat = np.zeros(shape, dtype=np.int64)
    low = np.full(shape, np.inf)
    high = np.full(shape, -np.inf)
    total = np.zeros(shape)
    np.add.at(rays.reshape(-1), hits.cell, 1)
    cell, height = hits.cell[hits.flat], hits.height[hits.flat]
    np.add.at(flat.reshape(-1), cell, 1)
    np.minimum.at(low.reshape(-1), cell, height)
    np.maximum.at(high.reshape(-1), cell, height)
    np.add.at(total.reshape(-1), cell, height)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(flat > 0, total / flat, np.nan)
    return _RayStats(rays, flat, low, high, mean)


def _shifted[T: np.generic](
    values: NDArray[T], dx: int, dy: int, *, fill: object
) -> NDArray[T]:
    """``values`` seen from the cell ``(x + dx, y + dy)`` (``fill`` outside)."""
    out = np.full_like(values, fill)
    nx, ny = values.shape[:2]
    xs = slice(max(dx, 0), nx + min(dx, 0))
    ys = slice(max(dy, 0), ny + min(dy, 0))
    xd = slice(max(-dx, 0), nx + min(-dx, 0))
    yd = slice(max(-dy, 0), ny + min(-dy, 0))
    out[xd, yd] = values[xs, ys]
    return out
