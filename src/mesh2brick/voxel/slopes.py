# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Where a slope lies closer to the input mesh than the voxel stair (ROADMAP 8).

Voxels turn every tilted surface into stairs. A slope brick (3040b and 3039:
45°, one stud deep; 4286: 33°, two studs deep) can replace a stair tread, but
only the mesh knows whether that brings the model closer to it: depending on
where the surface crosses the cells, the tread is better left as it is. So the
voxelizer, while it still has the mesh, rates every possible slope (ADR 0021):

1. **Candidates.** A slope stands on one layer: its *stud column* is a filled
   cell, its *slope columns* (one or two) lie next to it, in one of the four
   directions. Each slope column is either a filled top cell (the slope cuts
   the stair's edge off) or an empty cell on top of a filled one (the slope
   fills the corner of the stair, adding material beyond the voxels).
2. **Tilt.** The mesh above the slope columns must be tilted the slope's way:
   the mean normal of the up-facing surface the vertical rays cross near the
   cell tilts between :data:`TILT_DEG` for the kind and points within
   :data:`MAX_TURN_DEG` of the slope's descent. Flat faces (tiles) and level
   or vertical surfaces never get slopes.
3. **Gain.** Along every vertical ray of the slope columns (the same 4 x 4
   rays per cell as the voxelization) the length where bricks and mesh
   disagree is measured for the stair and for the slope (its face falls from
   the full brick height to a lip of :data:`LIP_CELLS`; tops with studs count
   their stud). The *gain* is how much less the slope disagrees, as a mean
   thickness in LEGO millimetres over its slope columns. That volume between
   bricks and mesh is, for a gently curved surface, its distance integrated
   over the surface, so a positive gain means a smaller surface deviation
   (:mod:`mesh2brick.fidelity`).

The result is one gain per stud cell, direction and kind (``NaN``: no
candidate or no gain); the placement backend turns the best ones into slopes.
Only watertight meshes (inside and outside along a ray are known) on brick
cells get candidates. Pure functions on arrays, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np

from mesh2brick.voxel.rays import JITTER, ray_hits

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from mesh2brick.voxel.voxelize import Lattice

DIRECTIONS: Final = ((1, 0), (-1, 0), (0, 1), (0, -1))
"""Descent directions ``(dx, dy)`` of a slope, index 0-3 of the gain array."""
RUNS: Final = (1, 2)
"""Slope columns per kind, index 0-1: 45° (3040b, 3039) and 33° (4286)."""
TILT_DEG: Final = ((15.0, 85.0), (8.0, 60.0))
"""Surface tilt (from horizontal) each kind may replace, per index of :data:`RUNS`."""
MAX_TURN_DEG: Final = 50.0
"""The surface must fall at most this far off the slope's descent direction."""
LIP_CELLS: Final = 1.0 / 6.0
"""Height of the vertical edge at the low end: 4 of the 24 LDU of a brick."""
MIN_GAIN_MM: Final = 0.5
"""Slopes that bring their columns less than this much closer to the mesh (mean
over the sloped columns) are not worth a part: the stair stays (measured on
sphere and toadstool: the same deviation with 8 % fewer slopes than at 0)."""
STUD_HEIGHT_MM: Final = 1.7
STUD_RADIUS: Final = 0.3
"""Stud radius in studs (2.4 of 8 mm): the rays within it hit the stud."""
_HALF: Final = 0.5


@dataclass(frozen=True, slots=True)
class RayProfiles:
    """Inside length below every height, per vertical ray of a lattice.

    Breakpoints are sorted by ``key = ray * stride + height`` (heights in cell
    layers, shifted by +1 so every ray starts with a breakpoint at 0, i.e.
    one cell below the lattice); ``cum`` is the inside length from there up
    to the breakpoint, ``inside`` whether the stretch after it is inside the
    mesh.
    """

    key: NDArray[np.float64]
    cum: NDArray[np.float64]
    inside: NDArray[np.bool_]
    stride: float

    def inside_below(
        self, ray: NDArray[np.int64], height: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Inside length of ``ray`` from below the lattice up to ``height``."""
        query = ray * self.stride + (height + 1.0)
        index = np.searchsorted(self.key, query, side="right") - 1
        base = self.key[index]
        own = np.floor(base / self.stride + 1e-9) == ray
        cum = np.where(own, self.cum[index], 0.0)
        slope = np.where(own & self.inside[index], 1.0, 0.0)
        result: NDArray[np.float64] = cum + slope * (query - base)
        return result


@dataclass(frozen=True, slots=True)
class _Crossings:
    """Every crossing of the vertical rays with the mesh (cell layers)."""

    ray: NDArray[np.int64]
    height: NDArray[np.float64]
    sign: NDArray[np.int8]
    normal: NDArray[np.float64]
    """Unit normal of the crossed triangle, ``(k, 3)``, lattice units."""


def slope_gains(
    triangles: NDArray[np.float64],
    occupancy: NDArray[np.bool_],
    lattice: Lattice,
    flat: NDArray[np.float32],
    *,
    lego_cell_height_mm: float,
    samples: int = 4,
) -> NDArray[np.float32]:
    """Gain of every possible slope, ``float32[x, y, z, 4, 2]`` (mm, ``NaN``: none).

    Indexed by the slope's stud cell, its descent direction (:data:`DIRECTIONS`)
    and kind (:data:`RUNS`). Only positive gains are kept.

    Args:
        triangles: ``(m, 3, 3)`` watertight mesh triangles in model mm,
            outward winding.
        occupancy: the voxel grid on ``lattice`` (brick cells).
        lattice: where the cells sit in model space.
        flat: the flat tops (:func:`mesh2brick.voxel.flat.flat_tops`), which
            keep their tiles instead.
        lego_cell_height_mm: real height of one cell (9.6 mm).
        samples: rays per cell and horizontal axis.
    """
    shape = occupancy.shape
    gains = np.full((*shape, len(DIRECTIONS), len(RUNS)), np.nan, dtype=np.float32)
    if not occupancy.any() or not len(triangles):
        return gains
    crossings = _crossings(triangles, lattice, occupancy.shape, samples)
    if not len(crossings.ray):
        return gains
    profiles = ray_profiles(crossings, nz=shape[2])
    normals, counts = _surface_normals(crossings, shape, samples)
    stud = STUD_HEIGHT_MM / lego_cell_height_mm
    for d, (dx, dy) in enumerate(DIRECTIONS):
        for k, run in enumerate(RUNS):
            cells = _candidates(occupancy, flat, (dx, dy), run)
            cells &= _tilted(
                normals,
                counts,
                samples=samples,
                direction=(dx, dy),
                run=run,
                window=TILT_DEG[k],
            )
            at = np.argwhere(cells)
            if not len(at):
                continue
            gain = _gain(
                at,
                occupancy,
                profiles,
                direction=(dx, dy),
                run=run,
                samples=samples,
                stud=stud,
            )
            mm = gain * lego_cell_height_mm
            keep = mm > 0
            hit = at[keep]
            gains[hit[:, 0], hit[:, 1], hit[:, 2], d, k] = mm[keep]
    return gains


def worth_a_slope(gains: NDArray[np.float32], min_gain: float = MIN_GAIN_MM) -> int:
    """Stud cells with at least one slope worth placing (part estimate)."""
    good = np.isfinite(gains) & (gains >= min_gain)
    return int(good.any(axis=(3, 4)).sum())


# --------------------------------------------------------------------------- rays
def _crossings(
    triangles: NDArray[np.float64],
    lattice: Lattice,
    shape: tuple[int, ...],
    samples: int,
) -> _Crossings:
    """All crossings of the ``samples x samples`` rays per column with the mesh."""
    nx, ny, _ = shape
    nv = ny * samples
    step = lattice.pitch / samples
    ox, oy, oz = lattice.origin
    u = (triangles[:, :, 0] - ox) / step - 0.5 - JITTER[0]
    v = (triangles[:, :, 1] - oy) / step - 0.5 - JITTER[1]
    w = (triangles[:, :, 2] - oz) / lattice.cell_height
    # Model millimetres scale like LEGO ones (a cell is 1.2 studs high in
    # both), so these normals tilt as the real surface does.
    edges = triangles[:, 1:] - triangles[:, :1]
    raw = np.cross(edges[:, 0], edges[:, 1])
    length = np.linalg.norm(raw, axis=1)
    unit = raw / np.where(length > 0, length, 1.0)[:, None]
    rays: list[NDArray[np.int64]] = []
    heights: list[NDArray[np.float64]] = []
    signs: list[NDArray[np.int8]] = []
    tris: list[NDArray[np.int64]] = []
    for hits in ray_hits(u, v, nx * samples, nv):
        rays.append(hits.ray_i * nv + hits.ray_j)
        heights.append(np.einsum("ij,ij->i", hits.bary, w[hits.triangle]))
        signs.append(hits.sign)
        tris.append(hits.triangle)
    if not rays:
        empty = np.zeros(0, dtype=np.int64)
        return _Crossings(empty, np.zeros(0), np.zeros(0, np.int8), np.zeros((0, 3)))
    tri = np.concatenate(tris)
    return _Crossings(
        ray=np.concatenate(rays),
        height=np.concatenate(heights),
        sign=np.concatenate(signs),
        normal=unit[tri],
    )


def ray_profiles(crossings: _Crossings, *, nz: int) -> RayProfiles:
    """Inside length below every height, along each ray (:class:`RayProfiles`)."""
    stride = float(nz + 4)
    height = np.clip(crossings.height, -0.5, nz + 2.0) + 1.0
    order = np.lexsort((height, crossings.ray))
    ray, height, sign = crossings.ray[order], height[order], crossings.sign[order]
    starts = np.flatnonzero(np.r_[True, ray[1:] != ray[:-1]])
    # One breakpoint at the bottom of every ray that has crossings.
    first_rays = ray[starts]
    ray = np.insert(ray, starts, first_rays)
    height = np.insert(height, starts, 0.0)
    sign = np.insert(sign, starts, 0).astype(np.int64)
    starts = np.flatnonzero(np.r_[True, ray[1:] != ray[:-1]])
    sizes = np.diff(np.r_[starts, len(ray)])
    winding = np.cumsum(sign)
    winding -= np.repeat(winding[starts] - sign[starts], sizes)
    same_ray = np.r_[ray[1:] == ray[:-1], False]
    inside = same_ray & (winding > 0)
    length = np.where(inside, np.r_[np.diff(height), 0.0], 0.0)
    total = np.cumsum(length)
    before = np.repeat(np.r_[0.0, total][starts], sizes)
    cum = np.r_[0.0, total[:-1]] - before
    key = ray.astype(np.float64) * stride + height
    return RayProfiles(key=key, cum=cum, inside=inside, stride=stride)


def _surface_normals(
    crossings: _Crossings, shape: tuple[int, ...], samples: int
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Per cell: summed unit normals and count of up-facing crossings nearby.

    A crossing at height ``h`` counts for every cell whose window
    ``[z - 0.5, z + 1.5)`` holds it: the surface a slope in that cell would
    replace runs through the cell or just above or below it.
    """
    nx, ny, nz = shape
    nv = ny * samples
    up = crossings.sign < 0  # the rays point up: they leave through up-facing faces
    ray, height, normal = crossings.ray[up], crossings.height[up], crossings.normal[up]
    x = (ray // nv) // samples
    y = (ray % nv) // samples
    sums = np.zeros((nx * ny * nz, 3))
    counts = np.zeros(nx * ny * nz, dtype=np.int64)
    for low in (np.floor(height - _HALF), np.floor(height + _HALF)):
        z = low.astype(np.int64)
        ok = (z >= 0) & (z < nz)
        cell = (x[ok] * ny + y[ok]) * nz + z[ok]
        np.add.at(sums, cell, normal[ok])
        np.add.at(counts, cell, 1)
    return sums.reshape(nx, ny, nz, 3), counts.reshape(nx, ny, nz)


# --------------------------------------------------------------------------- candidates
def _shift(values: NDArray[np.bool_], dx: int, dy: int, dz: int) -> NDArray[np.bool_]:
    """``values`` seen from cell ``(x + dx, y + dy, z + dz)`` (``False`` outside)."""
    out = np.zeros_like(values)
    src = tuple(
        slice(max(d, 0), n + min(d, 0))
        for d, n in zip((dx, dy, dz), values.shape, strict=True)
    )
    dst = tuple(
        slice(max(-d, 0), n + min(-d, 0))
        for d, n in zip((dx, dy, dz), values.shape, strict=True)
    )
    out[dst] = values[src]
    return out


def _inside(shape: tuple[int, ...], dx: int, dy: int) -> NDArray[np.bool_]:
    """Cells whose neighbour ``(x + dx, y + dy)`` lies in the grid."""
    ok = np.ones(shape, dtype=bool)
    return _shift(ok, dx, dy, 0)


def _candidates(
    occupancy: NDArray[np.bool_],
    flat: NDArray[np.float32],
    direction: tuple[int, int],
    run: int,
) -> NDArray[np.bool_]:
    """Stud cells that could carry a slope of ``run`` columns falling ``direction``."""
    dx, dy = direction
    level = np.isfinite(flat)
    cells = occupancy.copy()
    for step in range(1, run + 1):
        sx, sy = dx * step, dy * step
        inside = _inside(occupancy.shape, sx, sy)
        filled = _shift(occupancy, sx, sy, 0)
        above = _shift(occupancy, sx, sy, 1)
        below = _shift(occupancy, sx, sy, -1)
        cut = filled & ~above & ~_shift(level, sx, sy, 0)
        add = ~filled & below & ~above & ~_shift(level, sx, sy, -1)
        cells &= inside & (cut | add)
    return cells


def _tilted(
    normals: NDArray[np.float64],
    counts: NDArray[np.int64],
    *,
    samples: int,
    direction: tuple[int, int],
    run: int,
    window: tuple[float, float],
) -> NDArray[np.bool_]:
    """Stud cells whose slope columns lie under a surface tilted the slope's way."""
    dx, dy = direction
    total = np.linalg.norm(normals, axis=3)
    horizontal = normals[..., 0] * dx + normals[..., 1] * dy
    sideways = np.hypot(normals[..., 0], normals[..., 1])
    with np.errstate(invalid="ignore", divide="ignore"):
        tilt = np.degrees(np.arctan2(sideways, normals[..., 2]))
        turn = horizontal / sideways
    low, high = window
    good = (
        (counts * 2 >= samples * samples)
        & (total > 0)
        & (tilt >= low)
        & (tilt <= high)
        & (turn >= math.cos(math.radians(MAX_TURN_DEG)))
    )
    cells = np.ones_like(good)
    for step in range(1, run + 1):
        cells &= _shift(good, dx * step, dy * step, 0)
    return cells


# --------------------------------------------------------------------------- gain
def _gain(
    at: NDArray[np.int64],
    occupancy: NDArray[np.bool_],
    profiles: RayProfiles,
    *,
    direction: tuple[int, int],
    run: int,
    samples: int,
    stud: float,
) -> NDArray[np.float64]:
    """Mean disagreement saved per ray (cells) by a slope at each stud cell ``at``."""
    nv = occupancy.shape[1] * samples
    dx, dy = direction
    sub = (np.arange(samples) + 0.5) / samples
    a, b = (
        g.ravel()
        for g in np.meshgrid(np.arange(samples), np.arange(samples), indexing="ij")
    )
    central = (np.abs(sub[a] - _HALF) < STUD_RADIUS) & (
        np.abs(sub[b] - _HALF) < STUD_RADIUS
    )
    along = sub[a] if dx else sub[b]
    if dx < 0 or dy < 0:
        along = 1.0 - along
    total = np.zeros(len(at))
    z = at[:, 2].astype(np.float64)
    for step in range(1, run + 1):
        cx = at[:, 0] + dx * step
        cy = at[:, 1] + dy * step
        filled = occupancy[cx, cy, at[:, 2]]
        ray = ((cx[:, None] * samples + a[None, :]) * nv) + (
            cy[:, None] * samples + b[None, :]
        )
        stud_here = np.where(central, stud, 0.0)[None, :]
        t_step = np.where(filled[:, None], 1.0 + stud_here, stud_here)
        u = (step - 1) + along[None, :]
        t_slope = np.broadcast_to(1.0 - (1.0 - LIP_CELLS) * u / run, t_step.shape)
        base = z[:, None]
        inside_step = profiles.inside_below(ray.ravel(), (base + t_step).ravel())
        inside_slope = profiles.inside_below(ray.ravel(), (base + t_slope).ravel())
        saved = (t_step - t_slope).ravel() - 2.0 * (inside_step - inside_slope)
        total += saved.reshape(len(at), -1).sum(axis=1)
    result: NDArray[np.float64] = total / (samples * samples * run)
    return result
