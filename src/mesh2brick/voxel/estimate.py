# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Part count of a voxel grid before placement (``inspect``, ``convert``).

The estimate retraces what legolization does (ADR 0019, docs/benchmarks.md
"Part estimate (Roadmap 5)"):

1. It works on plates: a brick-unit grid becomes three plate layers per cell
   and is hollowed the way legolization hollows it (``wall_thickness`` studs
   sideways, ``wall_thickness`` cells up and down).
2. Columns filled in one colour across a whole three-plate slab become
   bricks, everything else plates; every layer is tiled with the largest
   parts that fit (:func:`quick_fill`). legolization's own tiling needs about
   as many parts.
3. What that tiling leaves in separate pieces, legolization joins by
   rebuilding the area from 1 x 1 plates and merging them at random, which
   costs several times the parts. Two kinds of areas are rebuilt:

   - areas one cell high with nothing above or below (a courtyard, a base
     plate, a table top): bricks cannot hold each other there, so they
     become three layers of small plates;
   - a floor at most ``wall_thickness`` cells thick on a wide area (the
     bottom of a hollow box): rebuilt either as plates as well or, when
     legolization's final merge wins them back, as small bricks. Which one
     cannot be told beforehand, so the range is wide there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
from scipy import ndimage

from mesh2brick.voxel.grid import PLATES_PER_BRICK

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from mesh2brick.voxel.grid import VoxelGrid

FOOTPRINTS: Final = ((2, 8), (2, 6), (2, 4), (2, 3), (2, 2), (1, 8), (1, 6), (1, 4))
"""Brick/plate footprints (studs) for the quick fill, beside 1 x 3, 1 x 2, 1 x 1."""
_SHAPES: Final = tuple(
    sorted(
        {s for w, d in (*FOOTPRINTS, (1, 3), (1, 2), (1, 1)) for s in ((w, d), (d, w))},
        key=lambda s: (-s[0] * s[1], s),
    )
)
TILED_RANGE: Final = (0.85, 1.35)
"""Placed parts per part of the quick fill outside rebuilt areas (low, high).
Measured on 15 conversions: 0.88-1.27 (docs/benchmarks.md)."""
THIN_PER_CELL: Final = (0.55, 0.7, 0.9)
"""Parts per cell (1 stud x 1 brick) of a rebuilt area one cell high (low,
typical, high): three layers of plates of about 4 studs. Measured 0.66-0.81."""
FLOOR_PER_CELL: Final = (
    (1_000, (0.15, 0.45, 0.9)),
    (None, (0.55, 0.7, 0.9)),
)
"""Parts per cell of a rebuilt floor (low, typical, high) by the size of the
bottom layer's largest piece (studs, below the bound). Up to about 30 x 30
studs legolization either merges the floor back into small bricks (boxes 18
and 24 studs wide, two bodies: 0.18-0.24) or leaves plates (a 24-stud box 27
cells high, a 28-stud box: 0.52-0.82); wider floors stayed plates (32 x 32
studs, cubes, castle: 0.66-0.87)."""
THIN_ONE_PART: Final = 16
"""One-cell-high pieces up to this many studs are not rebuilt: one 2 x 8 part
covers them, or they hang on a part beside them."""
WEAK_FLOOR_STUDS: Final = 150
"""A floor gets rebuilt when at least this many studs of the bottom layer are
at most ``wall_thickness`` cells thick (measured: 196 rebuilt, 96 not)."""
MAX_FILL_CELLS: Final = 500_000
"""Bigger shells (plate cells) are estimated from their size: the fill is a
Python loop over the shell, about 2 seconds for 500,000 plate cells at worst
(a sphere of 128 studs has 320,000 and takes 1.3 s)."""
CELLS_PER_PART: Final = 4.0
"""Fallback: shell cells (1 stud x 1 brick) per placed part (measured 3.2-6.0)."""
FALLBACK_RANGE: Final = (0.6, 1.6)
"""Range of the fallback, wide because it does not look at the shape."""

_FACE: Final = ndimage.generate_binary_structure(3, 1)
_Z_LINE: Final = np.zeros((3, 3, 3), dtype=bool)
_Z_LINE[1, 1, :] = True
_XY_CROSS: Final = np.zeros((3, 3, 3), dtype=bool)
_XY_CROSS[:, 1, 1] = _XY_CROSS[1, :, 1] = True


@dataclass(frozen=True, slots=True)
class PartsEstimate:
    """Expected part count of the converted model, with a range."""

    low: int
    expected: int
    high: int
    tiled: int = 0
    """Parts of the quick fill outside rebuilt areas."""
    thin_cells: int = 0
    """Cells (1 stud x 1 brick) of areas one cell high that become plates."""
    floor_cells: int = 0
    """Cells of a thin, wide floor that legolization rebuilds."""


def parts_estimate(
    grid: VoxelGrid, *, hollow: bool = True, wall_thickness: int = 2
) -> PartsEstimate:
    """Expected part count of ``grid`` once placed, with a range.

    ``hollow`` and ``wall_thickness`` are ``voxel.fill == "hollow"`` and
    ``voxel.wall_thickness``.

    Raises:
        ValueError: if ``wall_thickness`` is below 1.
    """
    plates, colours = _plate_layers(grid)
    shell = _shell(plates, grid, wall_thickness) if hollow else plates
    total = int(shell.sum())
    if not total:
        return PartsEstimate(low=0, expected=0, high=0)
    if total > MAX_FILL_CELLS:
        return _scaled(total / PLATES_PER_BRICK / CELLS_PER_PART, FALLBACK_RANGE)
    filled, shell_slabs = _slabs(plates).any(axis=3), _slabs(shell).any(axis=3)
    thin = _thin(filled, shell_slabs)
    floor = _weak_floor(shell_slabs, wall_thickness * grid.plates_per_cell) & ~thin
    floor_rates = _floor_rates(_largest_area(shell_slabs[:, :, 0]))
    rebuilt = np.repeat(floor | thin, PLATES_PER_BRICK, axis=2)
    bricks = _brick_slabs(shell, colours)
    tiled = _fill_layers(bricks & ~(floor | thin), colours[:, :, ::PLATES_PER_BRICK])
    tiled += _fill_layers(
        shell & ~np.repeat(bricks, PLATES_PER_BRICK, axis=2) & ~rebuilt, colours
    )
    thin_cells = int((shell & np.repeat(thin, PLATES_PER_BRICK, axis=2)).sum())
    floor_cells = int((shell & np.repeat(floor, PLATES_PER_BRICK, axis=2)).sum())
    thin_cells, floor_cells = (
        round(n / PLATES_PER_BRICK) for n in (thin_cells, floor_cells)
    )
    bounds = (
        max(1, round(tiled * t + thin_cells * a + floor_cells * f))
        for t, a, f in zip(
            (TILED_RANGE[0], 1.0, TILED_RANGE[1]),
            THIN_PER_CELL,
            floor_rates,
            strict=True,
        )
    )
    low, expected, high = bounds
    return PartsEstimate(
        low=low,
        expected=expected,
        high=high,
        tiled=tiled,
        thin_cells=thin_cells,
        floor_cells=floor_cells,
    )


def plate_shell(grid: VoxelGrid, *, wall_thickness: int) -> NDArray[np.bool_]:
    """The plate cells legolization keeps when it hollows ``grid``.

    ``bool[x, y, plate]``, topped up with empty plates to whole slabs of
    three; the rule of legolization's ``core_mask`` (``wall_thickness`` studs
    sideways, ``wall_thickness`` cells up and down).

    Raises:
        ValueError: if ``wall_thickness`` is below 1.
    """
    plates, _ = _plate_layers(grid)
    return _shell(plates, grid, wall_thickness)


def quick_fill(occupancy: NDArray[np.bool_]) -> int:
    """Parts a layer-by-layer greedy fill with the largest bricks needs.

    Every layer is scanned cell by cell; the first free cell gets the largest
    footprint (either orientation) that fits into free cells. A quick stand-in
    for placement, used only for the estimate.
    """
    return sum(_fill_layer(occupancy[:, :, z]) for z in range(occupancy.shape[2]))


# --------------------------------------------------------------------------- helpers
def _fill_layer(free: NDArray[np.bool_]) -> int:
    free = free.copy()
    nx, ny = free.shape
    parts = 0
    for x, y in np.argwhere(free):
        if not free[x, y]:
            continue
        for w, d in _SHAPES:
            if x + w <= nx and y + d <= ny and free[x : x + w, y : y + d].all():
                free[x : x + w, y : y + d] = False
                parts += 1
                break
    return parts


def _fill_layers(mask: NDArray[np.bool_], colours: NDArray[np.int32]) -> int:
    """:func:`quick_fill` with one colour per part."""
    parts = 0
    for z in range(mask.shape[2]):
        layer = mask[:, :, z]
        if not layer.any():
            continue
        codes = colours[:, :, z]
        for code in np.unique(codes[layer]):
            parts += _fill_layer(layer & (codes == code))
    return parts


def _plate_layers(grid: VoxelGrid) -> tuple[NDArray[np.bool_], NDArray[np.int32]]:
    """Occupancy and colours per plate, topped up to whole three-plate slabs."""
    plates = np.repeat(grid.occupancy, grid.plates_per_cell, axis=2)
    colours = np.repeat(grid.color, grid.plates_per_cell, axis=2)
    extra = -plates.shape[2] % PLATES_PER_BRICK
    if not extra:
        return plates, colours
    pad = ((0, 0), (0, 0), (0, extra))
    return np.pad(plates, pad), np.pad(colours, pad, constant_values=-1)


def _shell(
    plates: NDArray[np.bool_], grid: VoxelGrid, wall_thickness: int
) -> NDArray[np.bool_]:
    """Drop the cells legolization's ``core_mask`` hollows out."""
    if wall_thickness < 1:
        msg = "wall_thickness must be at least 1"
        raise ValueError(msg)
    margin_xy, margin_z = wall_thickness, wall_thickness * grid.plates_per_cell
    common = min(margin_xy, margin_z)
    core = ndimage.binary_erosion(
        plates, structure=_FACE, iterations=common, border_value=0
    )
    if margin_z > common:
        core = ndimage.binary_erosion(
            core, structure=_Z_LINE, iterations=margin_z - common, border_value=0
        )
    if margin_xy > common:
        core = ndimage.binary_erosion(
            core, structure=_XY_CROSS, iterations=margin_xy - common, border_value=0
        )
    return np.asarray(plates & ~core, dtype=bool)


def _slabs(array: NDArray[np.generic]) -> NDArray[np.generic]:
    nx, ny, nz = array.shape
    return array.reshape(nx, ny, nz // PLATES_PER_BRICK, PLATES_PER_BRICK)


def _brick_slabs(
    shell: NDArray[np.bool_], colours: NDArray[np.int32]
) -> NDArray[np.bool_]:
    """Slab columns filled in one colour across all three plates."""
    slab_colours = _slabs(colours)
    same = (slab_colours == slab_colours[..., :1]).all(axis=3)
    return np.asarray(_slabs(shell).all(axis=3) & same, dtype=bool)


def _thin(filled: NDArray[np.bool_], shell: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Shell slabs with no filled slab directly above or below.

    Pieces of up to :data:`THIN_ONE_PART` studs do not count.
    """
    neighbour = np.zeros_like(filled)
    neighbour[:, :, :-1] |= filled[:, :, 1:]
    neighbour[:, :, 1:] |= filled[:, :, :-1]
    thin = shell & ~neighbour
    for z in np.flatnonzero(thin.any(axis=(0, 1))):
        labels, _ = ndimage.label(thin[:, :, z])
        sizes = np.bincount(labels.ravel())
        small = sizes <= THIN_ONE_PART
        small[0] = True
        thin[:, :, z] &= ~small[labels]
    return np.asarray(thin, dtype=bool)


def _weak_floor(shell: NDArray[np.bool_], margin_plates: int) -> NDArray[np.bool_]:
    """The bottom slabs, if the floor is thin over a wide area; else nothing.

    A bottom column is weak when the shell above it ends within the floor
    thickness (``margin_plates``, at least one slab): air or the hollow core
    follows.
    """
    depth = max(1, -(-margin_plates // PLATES_PER_BRICK))
    floor = np.zeros_like(shell)
    if shell.shape[2] <= depth:
        weak = shell[:, :, 0]
    else:
        weak = shell[:, :, 0] & ~shell[:, :, depth]
    if int(weak.sum()) >= WEAK_FLOOR_STUDS:
        floor[:, :, :depth] = shell[:, :, :depth]
    return floor


def _largest_area(layer: NDArray[np.bool_]) -> int:
    labels, count = ndimage.label(layer)
    return int(np.bincount(labels.ravel())[1:].max()) if count else 0


def _floor_rates(studs: int) -> tuple[float, float, float]:
    for bound, rates in FLOOR_PER_CELL:
        if bound is None or studs < bound:
            return rates
    return FLOOR_PER_CELL[-1][1]


def _scaled(expected: float, factors: tuple[float, float]) -> PartsEstimate:
    low, high = factors
    return PartsEstimate(
        low=max(1, round(expected * low)),
        expected=max(1, round(expected)),
        high=max(1, round(expected * high)),
    )
