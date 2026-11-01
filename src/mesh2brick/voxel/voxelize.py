# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Mesh -> stud-raster voxel grid by volume fraction (column rasterization).

Algorithm (see ADR 0003):

1. **Lattice.** One cell is 1 x 1 stud horizontally and one brick (1.2 studs)
   or plate (0.4 studs) tall. Rounding rule: per horizontal axis the model
   gets ``round_half_up(extent / pitch)`` cells (at least 1) and is centred on
   them; vertically the lattice starts at the model's lowest point. The
   lattice is padded so no material can fall outside, and empty border cells
   are cropped at the end.
2. **Columns.** Every cell is sampled by ``S x S`` vertical rays. For each ray
   we collect where it crosses the surface and whether the surface faces
   down (entering, +1) or up (leaving, -1). Crossings are found for all
   triangles at once with numpy (bounding-box expansion + barycentric test),
   so multi-million-triangle meshes take seconds.
3. **Inside length.** Sorting a ray's crossings by height and summing the
   signs gives the winding number; where it is positive the ray is inside
   (overlapping bodies are unioned). The inside length is split exactly into
   the cells it passes through.
4. **Fraction.** A cell's filled fraction is the mean inside length of its
   rays divided by the cell height; cells reaching ``threshold`` are occupied.

Non-watertight meshes have no well-defined inside, so they fall back to
surface sampling plus hole filling (``method="surface"``).
"""

from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
import trimesh
from scipy import ndimage

from mesh2brick.voxel.color import apply_colors
from mesh2brick.voxel.grid import (
    EMPTY,
    LDU_PER_PLATE,
    LDU_PER_STUD,
    PLATES_PER_UNIT,
    VoxelGrid,
)

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from mesh2brick.config import Settings
    from mesh2brick.ingest.base import MeshModel
    from mesh2brick.voxel.grid import HeightUnit

DEFAULT_SAMPLES: Final = 4
"""Rays per stud and axis (4 x 4 = 16 rays per cell column)."""
_PAIR_CHUNK: Final = 4_000_000
"""Max (triangle, ray) candidate pairs held in memory at once."""
# Rays sit a hair off the regular sample positions so they (almost surely)
# never hit an edge or vertex exactly, which would double-count a crossing.
_JITTER: Final = (1.234567e-6, 2.345678e-6)
_MIN_AREA: Final = 1e-12
_SURFACE_SAMPLES_PER_RAY: Final = 4
_MAX_SURFACE_SAMPLES: Final = 5_000_000

Method = Literal["volume", "surface"]


@dataclass(frozen=True, slots=True)
class Lattice:
    """Where the voxel cells sit in model space (millimetres)."""

    origin: tuple[float, float, float]
    """Minimum corner of cell ``(0, 0, 0)``."""
    pitch: float
    """Horizontal cell size = model millimetres per stud."""
    cell_height: float
    shape: tuple[int, int, int]

    @property
    def cell_volume(self) -> float:
        """Volume of one cell in mm³."""
        return self.pitch * self.pitch * self.cell_height


@dataclass(frozen=True, slots=True)
class VoxelizeReport:
    """Numbers worth showing after voxelization."""

    method: Method
    pitch_mm: float
    cell_height_mm: float
    shape: tuple[int, int, int]
    filled_cells: int
    mesh_volume_mm3: float | None
    voxel_volume_mm3: float
    seconds: float

    @property
    def volume_error(self) -> float | None:
        """Relative volume deviation voxels vs. mesh (``None`` if unknown)."""
        if not self.mesh_volume_mm3:
            return None
        return (self.voxel_volume_mm3 - self.mesh_volume_mm3) / self.mesh_volume_mm3


@dataclass(frozen=True, slots=True)
class VoxelizeResult:
    """The grid plus a report and any warnings."""

    grid: VoxelGrid
    report: VoxelizeReport
    warnings: tuple[str, ...] = ()


# --------------------------------------------------------------------------- API
def voxelize(model: MeshModel, settings: Settings) -> VoxelizeResult:
    """Voxelize a normalised model according to ``settings`` (solid grid).

    Hollowing is *not* applied here: the placement backend hollows the solid
    grid itself so it can restore material where stability needs it (ADR 0004).
    Use :func:`hollow` for previews and statistics.
    """
    started = time.perf_counter()
    mesh = model.mesh
    pitch = model_pitch(np.asarray(mesh.extents), settings)
    unit: HeightUnit = settings.voxel.height_unit
    lattice = plan_lattice(np.asarray(mesh.bounds), pitch=pitch, height_unit=unit)
    warnings: list[str] = []
    method: Method
    if model.watertight:
        method = "volume"
        fractions = fill_fractions(np.asarray(mesh.triangles), lattice)
        occupancy = fractions >= settings.voxel.threshold - 1e-9
    else:
        method = "surface"
        occupancy = surface_occupancy(mesh, lattice)
    occupancy, origin = _crop(occupancy, lattice)
    if not occupancy.any():
        warnings.append(
            "no voxel reached the fill threshold; the model is too small or thin "
            "for this scale (increase input.target_studs or lower voxel.threshold)"
        )
    color = apply_colors(occupancy, settings.color)
    grid = VoxelGrid(
        occupancy=occupancy,
        color=color,
        height_unit=unit,
        pitch_mm=lattice.pitch,
        origin_mm=origin,
    )
    report = VoxelizeReport(
        method=method,
        pitch_mm=lattice.pitch,
        cell_height_mm=lattice.cell_height,
        shape=grid.shape,
        filled_cells=grid.filled_count,
        mesh_volume_mm3=float(mesh.volume) if model.watertight else None,
        voxel_volume_mm3=grid.filled_count * lattice.cell_volume,
        seconds=time.perf_counter() - started,
    )
    return VoxelizeResult(grid=grid, report=report, warnings=tuple(warnings))


def model_pitch(extents: NDArray[np.float64], settings: Settings) -> float:
    """Model millimetres per stud for the configured scale mode.

    ``studs``: the longest axis (any direction, measured in studs of 8 mm
    proportion) becomes ``target_studs`` long. ``mm``: ``mm_per_stud``.

    Raises:
        ValueError: for a mesh without extent.
    """
    if settings.input.scale_mode == "mm":
        return settings.input.mm_per_stud
    longest = float(np.max(extents))
    if not longest > 0:
        msg = "the mesh has no extent"
        raise ValueError(msg)
    return longest / settings.input.target_studs


def plan_lattice(
    bounds: NDArray[np.float64], *, pitch: float, height_unit: HeightUnit
) -> Lattice:
    """Lattice for a model with ``bounds`` (2 x 3, mm) per the rounding rule."""
    low, high = bounds
    extent = high - low
    cell_height = pitch * PLATES_PER_UNIT[height_unit] * LDU_PER_PLATE / LDU_PER_STUD
    origin: list[float] = []
    shape: list[int] = []
    for axis in (0, 1):
        cells = max(1, round_half_up(extent[axis] / pitch))
        centre = (low[axis] + high[axis]) / 2
        # One padding cell per side catches material beyond the rounded width.
        origin.append(centre - (cells / 2 + 1) * pitch)
        shape.append(cells + 2)
    origin.append(float(low[2]))
    shape.append(max(1, math.ceil(extent[2] / cell_height - 1e-9)))
    return Lattice(
        origin=(origin[0], origin[1], origin[2]),
        pitch=pitch,
        cell_height=cell_height,
        shape=(shape[0], shape[1], shape[2]),
    )


def round_half_up(value: float) -> int:
    """Round to nearest integer, halves up (``round()`` would round to even)."""
    return math.floor(value + 0.5)


# --------------------------------------------------------------------------- core
def fill_fractions(
    triangles: NDArray[np.float64],
    lattice: Lattice,
    samples: int = DEFAULT_SAMPLES,
) -> NDArray[np.float64]:
    """Filled volume fraction (0..1) of every lattice cell.

    Args:
        triangles: ``(m, 3, 3)`` triangle corners in mm with outward winding.
        lattice: the cells to fill.
        samples: rays per cell and horizontal axis.
    """
    nx, ny, nz = lattice.shape
    nu, nv = nx * samples, ny * samples
    step = lattice.pitch / samples
    ox, oy, oz = lattice.origin
    # Ray (i, j) sits at u = i, v = j in these coordinates.
    u = (triangles[:, :, 0] - ox) / step - 0.5 - _JITTER[0]
    v = (triangles[:, :, 1] - oy) / step - 0.5 - _JITTER[1]
    w = (triangles[:, :, 2] - oz) / lattice.cell_height
    area = (u[:, 1] - u[:, 0]) * (v[:, 2] - v[:, 0]) - (u[:, 2] - u[:, 0]) * (
        v[:, 1] - v[:, 0]
    )
    keep = np.abs(area) > _MIN_AREA  # vertical faces are never crossed
    u, v, w, area = u[keep], v[keep], w[keep], area[keep]
    i0 = np.clip(np.ceil(u.min(axis=1)), 0, nu).astype(np.int64)
    i1 = np.clip(np.floor(u.max(axis=1)), -1, nu - 1).astype(np.int64)
    j0 = np.clip(np.ceil(v.min(axis=1)), 0, nv).astype(np.int64)
    j1 = np.clip(np.floor(v.max(axis=1)), -1, nv - 1).astype(np.int64)
    width_j = np.maximum(j1 - j0 + 1, 0)
    counts = np.maximum(i1 - i0 + 1, 0) * width_j

    columns: list[NDArray[np.int64]] = []
    heights: list[NDArray[np.float64]] = []
    signs: list[NDArray[np.int8]] = []
    for chunk in _chunks(counts, _PAIR_CHUNK):
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
        tri, b0, b1, b2 = tri[hit], b0[hit], b1[hit], b2[hit]
        columns.append(ray_i[hit] * nv + ray_j[hit])
        heights.append(b0 * w[tri, 0] + b1 * w[tri, 1] + b2 * w[tri, 2])
        # Counter-clockwise from above = normal points up = the ray leaves.
        signs.append(np.where(area[tri] > 0, -1, 1).astype(np.int8))

    filled = np.zeros(nu * nv * nz, dtype=np.float64)
    if columns:
        _accumulate_inside(
            np.concatenate(columns),
            np.concatenate(heights),
            np.concatenate(signs),
            nz,
            filled,
        )
    per_ray = filled.reshape(nx, samples, ny, samples, nz)
    fractions: NDArray[np.float64] = per_ray.sum(axis=(1, 3)) / (samples * samples)
    return np.clip(fractions, 0.0, 1.0)


def _accumulate_inside(
    column: NDArray[np.int64],
    height: NDArray[np.float64],
    sign: NDArray[np.int8],
    nz: int,
    out: NDArray[np.float64],
) -> None:
    """Add every ray's inside length (in cell heights) to ``out[column, cell]``."""
    order = np.lexsort((height, column))
    column, height, sign = column[order], height[order], sign[order]
    winding = np.cumsum(sign, dtype=np.int64)
    starts = np.flatnonzero(np.r_[True, column[1:] != column[:-1]])
    sizes = np.diff(np.r_[starts, len(column)])
    before = winding[starts] - sign[starts]
    winding -= np.repeat(before, sizes)
    # Interval k = [height[k], height[k+1]] is inside if the winding number
    # after crossing k is positive and k+1 is on the same ray.
    same_ray = np.r_[column[1:] == column[:-1], False]
    inside = np.flatnonzero(same_ray & (winding > 0))
    low = np.clip(height[inside], 0.0, nz)
    high = np.clip(height[inside + 1], 0.0, nz)
    ray = column[inside]
    valid = high > low
    low, high, ray = low[valid], high[valid], ray[valid]
    first = np.floor(low).astype(np.int64)
    last = np.minimum(np.ceil(high).astype(np.int64) - 1, nz - 1)
    span = np.maximum(last - first + 1, 1)
    idx = np.repeat(np.arange(len(low)), span)
    cell = first[idx] + (np.arange(len(idx)) - np.repeat(np.cumsum(span) - span, span))
    overlap = np.minimum(high[idx], cell + 1) - np.maximum(low[idx], cell)
    out += np.bincount(
        ray[idx] * nz + cell, weights=np.maximum(overlap, 0.0), minlength=out.size
    )


def surface_occupancy(mesh: trimesh.Trimesh, lattice: Lattice) -> NDArray[np.bool_]:
    """Fallback for open meshes: cells touched by the surface, holes filled."""
    nx, ny, nz = lattice.shape
    spacing = lattice.pitch / DEFAULT_SAMPLES
    count = int(
        min(
            _MAX_SURFACE_SAMPLES,
            max(10_000, mesh.area / (spacing * spacing) * _SURFACE_SAMPLES_PER_RAY),
        )
    )
    points, _ = trimesh.sample.sample_surface(mesh, count, seed=0)
    points = np.concatenate([np.asarray(points), np.asarray(mesh.vertices)])
    size = np.array([lattice.pitch, lattice.pitch, lattice.cell_height])
    index = np.floor((points - np.asarray(lattice.origin)) / size).astype(np.int64)
    index = np.clip(index, 0, np.array([nx - 1, ny - 1, nz - 1]))
    shell = np.zeros(lattice.shape, dtype=bool)
    shell[index[:, 0], index[:, 1], index[:, 2]] = True
    filled: NDArray[np.bool_] = ndimage.binary_fill_holes(shell)
    return filled


def hollow(grid: VoxelGrid, wall_thickness: int) -> VoxelGrid:
    """Keep only cells within ``wall_thickness`` cells of the outside.

    Morphological erosion with face connectivity; the grid border counts as
    outside. Used for previews and material estimates - placement hollows the
    solid grid itself (ADR 0004).

    Raises:
        ValueError: if ``wall_thickness`` is below 1.
    """
    if wall_thickness < 1:
        msg = "wall_thickness must be at least 1"
        raise ValueError(msg)
    core = ndimage.binary_erosion(
        grid.occupancy,
        structure=ndimage.generate_binary_structure(3, 1),
        iterations=wall_thickness,
        border_value=0,
    )
    shell = grid.occupancy & ~core
    return VoxelGrid(
        occupancy=shell,
        color=np.where(shell, grid.color, EMPTY).astype(np.int32),
        height_unit=grid.height_unit,
        pitch_mm=grid.pitch_mm,
        origin_mm=grid.origin_mm,
    )


# --------------------------------------------------------------------------- helpers
def _chunks(counts: NDArray[np.int64], budget: int) -> list[slice]:
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


def _crop(
    occupancy: NDArray[np.bool_], lattice: Lattice
) -> tuple[NDArray[np.bool_], tuple[float, float, float]]:
    """Drop empty border cells; return the cropped mask and its new origin."""
    if not occupancy.any():
        return np.zeros((1, 1, 1), dtype=bool), lattice.origin
    filled = np.argwhere(occupancy)
    low, high = filled.min(axis=0), filled.max(axis=0) + 1
    cropped = occupancy[low[0] : high[0], low[1] : high[1], low[2] : high[2]]
    ox, oy, oz = lattice.origin
    origin = (
        ox + low[0] * lattice.pitch,
        oy + low[1] * lattice.pitch,
        oz + low[2] * lattice.cell_height,
    )
    return np.ascontiguousarray(cropped), origin
