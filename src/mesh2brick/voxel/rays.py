# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Regular ray grids crossing triangle meshes, vectorized with numpy.

Shared by the volume-fraction voxelizer (vertical rays) and the colour
transfer (rays along all three axes). Candidates come from the triangles'
bounding boxes; a barycentric test keeps the real crossings. Work is split
into chunks of at most ``PAIR_CHUNK`` (triangle, ray) pairs to bound memory.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterator

    from numpy.typing import NDArray

PAIR_CHUNK: Final = 4_000_000
"""Max (triangle, ray) candidate pairs held in memory at once."""
# Rays sit a hair off the regular sample positions so they (almost surely)
# never hit an edge or vertex exactly, which would double-count a crossing.
JITTER: Final = (1.234567e-6, 2.345678e-6)
MIN_AREA: Final = 1e-12
"""Projected areas below this count as parallel to the rays."""


@dataclass(frozen=True, slots=True)
class RayHits:
    """Where rays along one axis cross triangles (one chunk of results)."""

    triangle: NDArray[np.int64]
    """Index of the crossed triangle."""
    ray_i: NDArray[np.int64]
    ray_j: NDArray[np.int64]
    bary: NDArray[np.float64]
    """``(k, 3)`` barycentric coordinates of the crossing in its triangle."""
    sign: NDArray[np.int8]
    """+1 where the ray enters the solid, -1 where it leaves."""


def ray_hits(
    u: NDArray[np.float64], v: NDArray[np.float64], nu: int, nv: int
) -> Iterator[RayHits]:
    """Crossings of an ``nu x nv`` ray grid with triangles, in chunks.

    ``u``/``v`` are the ``(m, 3)`` triangle corners projected onto the plane
    perpendicular to the rays, in ray units: ray ``(i, j)`` sits at
    ``(u, v) = (i, j)``. The rays point along ``u x v``; a triangle whose
    projection is counter-clockwise faces along the rays, so they leave there.
    Triangles parallel to the rays are never crossed.
    """
    area = (u[:, 1] - u[:, 0]) * (v[:, 2] - v[:, 0]) - (u[:, 2] - u[:, 0]) * (
        v[:, 1] - v[:, 0]
    )
    candidates = np.flatnonzero(np.abs(area) > MIN_AREA)
    u, v, area = u[candidates], v[candidates], area[candidates]
    i0 = np.clip(np.ceil(u.min(axis=1)), 0, nu).astype(np.int64)
    i1 = np.clip(np.floor(u.max(axis=1)), -1, nu - 1).astype(np.int64)
    j0 = np.clip(np.ceil(v.min(axis=1)), 0, nv).astype(np.int64)
    j1 = np.clip(np.floor(v.max(axis=1)), -1, nv - 1).astype(np.int64)
    width_j = np.maximum(j1 - j0 + 1, 0)
    counts = np.maximum(i1 - i0 + 1, 0) * width_j
    for chunk in chunks(counts, PAIR_CHUNK):
        if not counts[chunk].sum():
            continue
        tri = np.repeat(np.arange(chunk.start, chunk.stop), counts[chunk])
        first = np.cumsum(counts[chunk]) - counts[chunk]
        local = np.arange(len(tri)) - np.repeat(first, counts[chunk])
        ray_i = i0[tri] + local // width_j[tri]
        ray_j = j0[tri] + local % width_j[tri]
        du = ray_i - u[tri, 0]
        dv = ray_j - v[tri, 0]
        b1 = (du * (v[tri, 2] - v[tri, 0]) - (u[tri, 2] - u[tri, 0]) * dv) / area[tri]
        b2 = ((u[tri, 1] - u[tri, 0]) * dv - du * (v[tri, 1] - v[tri, 0])) / area[tri]
        b0 = 1.0 - b1 - b2
        hit = (b0 >= 0) & (b1 >= 0) & (b2 >= 0)
        tri = tri[hit]
        yield RayHits(
            triangle=candidates[tri],
            ray_i=ray_i[hit],
            ray_j=ray_j[hit],
            bary=np.stack([b0[hit], b1[hit], b2[hit]], axis=1),
            sign=np.where(area[tri] > 0, -1, 1).astype(np.int8),
        )


def chunks(counts: NDArray[np.int64], budget: int) -> list[slice]:
    """Split triangle indices so each chunk has at most ~``budget`` pairs."""
    if not len(counts):
        return []
    total = np.cumsum(counts)
    bounds = [0]
    while bounds[-1] < len(counts):
        start = bounds[-1]
        offset = total[start - 1] if start else 0
        stop = int(np.searchsorted(total, offset + budget, side="right"))
        bounds.append(max(stop, start + 1))
    return [slice(a, b) for a, b in itertools.pairwise(bounds)]
