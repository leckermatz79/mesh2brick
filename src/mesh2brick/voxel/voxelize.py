# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Mesh -> stud-raster voxel grid by volume fraction (column rasterization).

Algorithm (see ADR 0003):

1. **Lattice.** One cell is 1 x 1 stud horizontally and one brick (1.2 studs)
   or plate (0.4 studs) tall. Rounding rule: per horizontal axis the model
   gets ``round_half_up(extent / pitch)`` cells (at least 1) and is centred on
   them; vertically the lattice starts at the model's lowest point. A target
   height in cm is rounded to whole cell layers first, so the model's height
   fills exactly that many layers (:func:`target_layers`). The
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

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
import trimesh
from scipy import ndimage

from mesh2brick.voxel.color import apply_colors, model_colors
from mesh2brick.voxel.flat import flat_tops
from mesh2brick.voxel.grid import (
    EMPTY,
    LDU_PER_PLATE,
    LDU_PER_STUD,
    LEGO_MM_PER_STUD,
    PLATES_PER_UNIT,
    VoxelGrid,
    lego_cell_height_mm,
)
from mesh2brick.voxel.rays import JITTER, ray_hits

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from mesh2brick.config import Settings
    from mesh2brick.ingest.base import MeshModel
    from mesh2brick.voxel.color import ColorQuantizer
    from mesh2brick.voxel.grid import HeightUnit

DEFAULT_SAMPLES: Final = 4
"""Rays per stud and axis (4 x 4 = 16 rays per cell column)."""
_SURFACE_SAMPLES_PER_RAY: Final = 4
_MAX_SURFACE_SAMPLES: Final = 5_000_000
_FACES: Final = ndimage.generate_binary_structure(3, 1)

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
def voxelize(
    model: MeshModel,
    settings: Settings,
    *,
    quantize: ColorQuantizer | None = None,
) -> VoxelizeResult:
    """Voxelize a normalised model according to ``settings`` (solid grid).

    Hollowing is *not* applied here: the placement backend hollows the solid
    grid itself so it can restore material where stability needs it (ADR 0004).
    Use :func:`hollow` for previews and statistics.

    Args:
        model: the normalised mesh.
        settings: voxel, scale and colour settings.
        quantize: matches model colours to LDraw codes; needed only when
            ``color.mode`` takes colours from a model that has some.
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
    occupancy, cleanup_notes = clean_up(
        occupancy, min_island_fraction=settings.voxel.min_island_fraction
    )
    warnings.extend(cleanup_notes)
    flat = flat_tops(
        np.asarray(mesh.triangles),
        occupancy,
        lattice,
        lego_cell_height_mm=lego_cell_height_mm(unit),
        overhang=settings.parts.tiles_overhang,
    )
    # Model colours use the full lattice: surface points in empty border cells
    # (details too thin to fill a cell) still colour their filled neighbours.
    full_color, color_notes = model_colors(
        occupancy, lattice, model, settings.color, quantize
    )
    warnings.extend(color_notes)
    box = _crop_box(occupancy)
    origin = _box_origin(box, lattice)
    occupancy = np.ascontiguousarray(occupancy[box])
    flat = np.ascontiguousarray(flat[box])
    color = (
        apply_colors(occupancy, settings.color)  # bands follow the cropped height
        if settings.color.mode == "height_bands"
        else np.ascontiguousarray(full_color[box])
    )
    if not occupancy.any():
        warnings.append(
            "no voxel reached the fill threshold; the model is too small or thin "
            "for this scale (make it bigger, e.g. --size 30cm, or lower "
            "voxel.threshold)"
        )
    grid = VoxelGrid(
        occupancy=occupancy,
        color=color,
        height_unit=unit,
        pitch_mm=lattice.pitch,
        origin_mm=origin,
        flat=flat,
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

    ``studs`` with ``target_height_cm``: the model gets :func:`target_layers`
    cell layers, exactly filling its height. ``studs`` otherwise: the longest
    axis (any direction, measured in studs of 8 mm proportion) becomes
    ``target_studs`` long. ``mm``: ``mm_per_stud``.

    Raises:
        ValueError: for a mesh without extent (or without height, when the
            height is what sets the scale).
    """
    if settings.input.scale_mode == "mm":
        return settings.input.mm_per_stud
    height_cm = settings.input.target_height_cm
    if height_cm is not None:
        height = float(extents[2])
        if not height > 0:
            msg = "the mesh has no height; give its size in studs (e.g. --size 32studs)"
            raise ValueError(msg)
        unit: HeightUnit = settings.voxel.height_unit
        studs_per_layer = lego_cell_height_mm(unit) / LEGO_MM_PER_STUD
        return height / (target_layers(height_cm, unit) * studs_per_layer)
    longest = float(np.max(extents))
    if not longest > 0:
        msg = "the mesh has no extent"
        raise ValueError(msg)
    return longest / settings.input.target_studs


def target_layers(height_cm: float, height_unit: HeightUnit) -> int:
    """Cell layers for a LEGO model ``height_cm`` tall: the nearest whole number.

    30 cm become 31 bricks (29.76 cm; 32 would be 30.72 cm) or 94 plates.
    """
    return max(1, round_half_up(height_cm * 10 / lego_cell_height_mm(height_unit)))


def scale_note(settings: Settings) -> str:
    """What sets the size, for summaries: ``" (height 30 cm -> 31 bricks)"``."""
    scale = settings.input
    if scale.scale_mode == "mm":
        return ""
    if scale.target_height_cm is None:
        return f" (longest axis -> {scale.target_studs} studs)"
    unit = settings.voxel.height_unit
    layers = target_layers(scale.target_height_cm, unit)
    return f" (height {scale.target_height_cm:g} cm -> {layers} {unit}s)"


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
    u = (triangles[:, :, 0] - ox) / step - 0.5 - JITTER[0]
    v = (triangles[:, :, 1] - oy) / step - 0.5 - JITTER[1]
    w = (triangles[:, :, 2] - oz) / lattice.cell_height
    columns: list[NDArray[np.int64]] = []
    heights: list[NDArray[np.float64]] = []
    signs: list[NDArray[np.int8]] = []
    for hits in ray_hits(u, v, nu, nv):
        tri = hits.triangle
        columns.append(hits.ray_i * nv + hits.ray_j)
        heights.append(np.einsum("ij,ij->i", hits.bary, w[tri]))
        signs.append(hits.sign)

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


HOLD_FOOTPRINTS: Final = ((1, 1), (1, 2), (1, 3), (1, 4), (1, 6), (1, 8))
HOLD_FOOTPRINTS_2: Final = ((2, 2), (2, 3), (2, 4), (2, 6), (2, 8))
"""Footprints of the standard bricks and plates (studs), both orientations."""


def holdable_cells(occupancy: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Cells that some straight brick or plate could hold in place.

    Parts only connect through studs, i.e. to the cell directly above or
    below; the bottom layer stands on the ground. A cell is holdable if a
    standard footprint (:data:`HOLD_FOOTPRINTS`) fits completely into the
    filled cells of its layer, covers the cell and touches at least one cell
    with a filled neighbour above or below.
    """
    below = np.ones_like(occupancy)  # the ground holds the bottom layer
    below[:, :, 1:] = occupancy[:, :, :-1]
    above = np.zeros_like(occupancy)
    above[:, :, :-1] = occupancy[:, :, 1:]
    supported = (occupancy & (below | above)).astype(np.int32)
    filled = occupancy.astype(np.int32)
    held = np.zeros_like(occupancy)
    nx, ny = occupancy.shape[:2]
    for w, length in (*HOLD_FOOTPRINTS, *HOLD_FOOTPRINTS_2):
        for a, b in {(w, length), (length, w)}:
            if a > nx or b > ny:
                continue
            fits = (_window_sums(filled, a, b) == a * b) & (
                _window_sums(supported, a, b) > 0
            )
            margin = ((a - 1, a - 1), (b - 1, b - 1), (0, 0))
            padded = np.pad(fits.astype(np.int32), margin)
            held |= _window_sums(padded, a, b) > 0  # covered by a fitting part
    return held & occupancy


def _window_sums(values: NDArray[np.int32], a: int, b: int) -> NDArray[np.int32]:
    """Sum over every ``a x b`` window of each layer (summed-area table)."""
    table = np.pad(values.cumsum(0).cumsum(1), ((1, 0), (1, 0), (0, 0)))
    sums: NDArray[np.int32] = (
        table[a:, b:] - table[:-a, b:] - table[a:, :-b] + table[:-a, :-b]
    )
    return sums


def drop_unholdable(
    occupancy: NDArray[np.bool_],
) -> tuple[NDArray[np.bool_], list[str]]:
    """Remove cells no part can hold (:func:`holdable_cells`), with a note.

    Such a cell floats or sticks out sideways with nothing above or below it
    within reach of any part, so its part would come loose (Duo at 48 studs:
    one cell of a two-cell stub). Removing a cell never takes away another
    cell's support, so one pass suffices (see :func:`clean_up`).
    """
    loose = occupancy & ~holdable_cells(occupancy)
    count = int(loose.sum())
    if not count:
        return occupancy, []
    note = (
        f"removed {count} cell(s) that no brick could hold (no straight brick or "
        "plate through them reaches a cell with something above or below)"
    )
    return occupancy & ~loose, [note]


def clean_up(
    occupancy: NDArray[np.bool_], *, min_island_fraction: float
) -> tuple[NDArray[np.bool_], list[str]]:
    """Remove small islands, then cells no part can hold, with notes.

    Islands go first, so a loose speck is reported as one. A removed
    unholdable cell may have been the only link of a small group, so the
    islands are checked again then.
    """
    occupancy, notes = remove_islands(occupancy, min_fraction=min_island_fraction)
    occupancy, held = drop_unholdable(occupancy)
    if held:
        occupancy, again = remove_islands(occupancy, min_fraction=min_island_fraction)
        notes = [*notes, *held, *(n for n in again if n not in notes)]
    return occupancy, notes


def remove_islands(
    occupancy: NDArray[np.bool_], *, min_fraction: float
) -> tuple[NDArray[np.bool_], list[str]]:
    """Drop face-disconnected islands smaller than ``min_fraction`` of all cells.

    A brick model has to be one connected piece; tiny islands (a thin tip that
    rounding cut off) would otherwise make the whole model unbuildable and
    send the backend into long rescue searches. Larger islands are kept and
    reported, because removing them would change the model visibly.
    """
    labels, count = ndimage.label(occupancy, structure=_FACES)
    if count <= 1:
        return occupancy, []
    sizes = np.bincount(labels.ravel())[1:]
    total = int(sizes.sum())
    largest = int(np.argmax(sizes))
    drop = [
        i
        for i, size in enumerate(sizes)
        if i != largest and size < min_fraction * total
    ]
    notes: list[str] = []
    result = occupancy
    if drop:
        result = occupancy & ~np.isin(labels, np.asarray(drop) + 1)
        removed = int(sizes[drop].sum())
        notes.append(
            f"removed {len(drop)} loose voxel island(s) with {removed} cell(s) "
            f"(below voxel.min_island_fraction={min_fraction:g})"
        )
    if kept := count - 1 - len(drop):
        notes.append(
            f"the model has {kept + 1} separate pieces; bricks cannot connect them "
            "(lower voxel.min_island_fraction or join them in the 3D model)"
        )
    return result, notes


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
        structure=_FACES,
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
        flat=None if grid.flat is None else np.where(shell, grid.flat, np.nan),
    )


# --------------------------------------------------------------------------- helpers
def _crop_box(occupancy: NDArray[np.bool_]) -> tuple[slice, slice, slice]:
    """Index box without empty border cells (one corner cell if all empty)."""
    if not occupancy.any():
        return (slice(0, 1), slice(0, 1), slice(0, 1))
    filled = np.argwhere(occupancy)
    low, high = filled.min(axis=0), filled.max(axis=0) + 1
    return (
        slice(int(low[0]), int(high[0])),
        slice(int(low[1]), int(high[1])),
        slice(int(low[2]), int(high[2])),
    )


def _box_origin(
    box: tuple[slice, slice, slice], lattice: Lattice
) -> tuple[float, float, float]:
    """Model-space minimum corner of the first cell in ``box``."""
    ox, oy, oz = lattice.origin
    return (
        ox + (box[0].start or 0) * lattice.pitch,
        oy + (box[1].start or 0) * lattice.pitch,
        oz + (box[2].start or 0) * lattice.cell_height,
    )
