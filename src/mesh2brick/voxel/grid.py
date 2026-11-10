# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The voxel grid: the hand-over format between voxelization and placement.

Conventions (binding for the whole code base):

* Axes are ``(x, y, z)`` with **z pointing up** and ``z = 0`` the ground layer.
* One voxel is 1 x 1 stud horizontally. Vertically it is one *height unit*:
  a brick (1.2 studs, 24 LDU) or a plate (0.4 studs, 8 LDU).
* ``color`` holds LDraw colour codes; unoccupied cells hold :data:`EMPTY`.

The conversion into LDraw coordinates (-Y up) happens in exactly one place,
the placement backend (see :mod:`mesh2brick.backends.legolization`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

HeightUnit = Literal["brick", "plate"]

EMPTY: Final = -1
"""Colour value of unoccupied cells."""

LDU_PER_STUD: Final = 20
LDU_PER_PLATE: Final = 8
PLATES_PER_BRICK: Final = 3
PLATES_PER_UNIT: Final[dict[HeightUnit, int]] = {"brick": PLATES_PER_BRICK, "plate": 1}
LEGO_MM_PER_STUD: Final = 8.0
"""Real stud pitch of a LEGO brick in millimetres."""
_NDIM: Final = 3


def lego_cell_height_mm(height_unit: HeightUnit) -> float:
    """Real height of one cell layer: 9.6 mm (brick) or 3.2 mm (plate)."""
    return (
        LEGO_MM_PER_STUD * PLATES_PER_UNIT[height_unit] * LDU_PER_PLATE / LDU_PER_STUD
    )


@dataclass(frozen=True, slots=True, eq=False)
class VoxelGrid:
    """An immutable, coloured occupancy grid on the stud raster.

    Attributes:
        occupancy: ``bool[x, y, z]`` - which cells are filled.
        color: ``int32[x, y, z]`` - LDraw colour code per cell, :data:`EMPTY`
            where unoccupied.
        height_unit: vertical size of one cell (``brick`` or ``plate``).
        pitch_mm: model millimetres per stud (horizontal cell size).
        origin_mm: model-space position of the minimum corner of cell
            ``(0, 0, 0)``, in millimetres.
        flat: ``float32[x, y, z]`` - for top cells whose top the input mesh
            renders flat (so they may get a tile, :mod:`mesh2brick.voxel.flat`):
            how far that face lies above the cell's top, in cell layers;
            ``NaN`` elsewhere. ``None`` when no mesh said so (voxel files):
            every top counts, at the height of the cells.
    """

    occupancy: NDArray[np.bool_]
    color: NDArray[np.int32]
    height_unit: HeightUnit = "brick"
    pitch_mm: float = 8.0
    origin_mm: tuple[float, float, float] = field(default=(0.0, 0.0, 0.0))
    flat: NDArray[np.float32] | None = None

    def __post_init__(self) -> None:
        occupancy = np.asarray(self.occupancy)
        color = np.asarray(self.color)
        if occupancy.ndim != _NDIM:
            msg = f"occupancy must be 3-D (x, y, z), got shape {occupancy.shape}"
            raise ValueError(msg)
        if occupancy.dtype != np.bool_:
            msg = f"occupancy must be boolean, got {occupancy.dtype}"
            raise ValueError(msg)
        if color.shape != occupancy.shape:
            msg = f"color shape {color.shape} != occupancy shape {occupancy.shape}"
            raise ValueError(msg)
        if not np.issubdtype(color.dtype, np.integer):
            msg = f"color must hold integer LDraw codes, got {color.dtype}"
            raise ValueError(msg)
        if self.height_unit not in PLATES_PER_UNIT:
            msg = f"height_unit must be 'brick' or 'plate', got {self.height_unit!r}"
            raise ValueError(msg)
        if not self.pitch_mm > 0:
            msg = f"pitch_mm must be positive, got {self.pitch_mm}"
            raise ValueError(msg)
        if np.any(color[~occupancy] != EMPTY):
            msg = "color must be EMPTY (-1) wherever occupancy is False"
            raise ValueError(msg)
        if np.any(color[occupancy] < 0):
            msg = "occupied cells need a non-negative LDraw colour code"
            raise ValueError(msg)
        if self.flat is not None:
            flat = np.asarray(self.flat, dtype=np.float32)
            if flat.shape != occupancy.shape:
                msg = f"flat must have the shape {occupancy.shape}"
                raise ValueError(msg)
            if np.any(np.isfinite(flat) & ~occupancy):
                msg = "flat marks cells that are not occupied"
                raise ValueError(msg)
            frozen_flat = flat.copy()
            frozen_flat.setflags(write=False)
            object.__setattr__(self, "flat", frozen_flat)
        frozen_occupancy = occupancy.copy()
        frozen_color = color.astype(np.int32, copy=True)
        frozen_occupancy.setflags(write=False)
        frozen_color.setflags(write=False)
        object.__setattr__(self, "occupancy", frozen_occupancy)
        object.__setattr__(self, "color", frozen_color)
        object.__setattr__(self, "origin_mm", tuple(float(v) for v in self.origin_mm))

    @classmethod
    def from_codes(
        cls,
        codes: NDArray[np.integer],
        *,
        height_unit: HeightUnit = "brick",
        pitch_mm: float = 8.0,
        origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> VoxelGrid:
        """Build a grid from a single code array (``-1`` = empty)."""
        array = np.asarray(codes)
        occupancy = array != EMPTY
        color = np.where(occupancy, array, EMPTY).astype(np.int32)
        return cls(
            occupancy=occupancy,
            color=color,
            height_unit=height_unit,
            pitch_mm=pitch_mm,
            origin_mm=origin_mm,
        )

    @property
    def shape(self) -> tuple[int, int, int]:
        """Grid extents ``(nx, ny, nz)`` in cells."""
        nx, ny, nz = self.occupancy.shape
        return (int(nx), int(ny), int(nz))

    @property
    def filled_count(self) -> int:
        """Number of occupied cells."""
        return int(np.count_nonzero(self.occupancy))

    @property
    def plates_per_cell(self) -> int:
        """How many plate heights one cell spans (3 for bricks, 1 for plates)."""
        return PLATES_PER_UNIT[self.height_unit]

    @property
    def cell_size_mm(self) -> tuple[float, float, float]:
        """Physical cell size ``(dx, dy, dz)`` in model millimetres."""
        dz = self.pitch_mm * self.plates_per_cell * LDU_PER_PLATE / LDU_PER_STUD
        return (self.pitch_mm, self.pitch_mm, dz)

    def flat_tops(self) -> NDArray[np.float32]:
        """:attr:`flat`, or every top cell at the height of the cells (offset 0)."""
        if self.flat is not None:
            return self.flat
        tops = self.occupancy.copy()
        tops[:, :, :-1] &= ~self.occupancy[:, :, 1:]
        offset: NDArray[np.float32] = np.where(tops, 0.0, np.nan).astype(np.float32)
        return offset

    @property
    def colors_used(self) -> tuple[int, ...]:
        """Sorted distinct LDraw colour codes of occupied cells."""
        return tuple(int(c) for c in np.unique(self.color[self.occupancy]))

    def to_codes(self) -> NDArray[np.int16]:
        """Single code array (``-1`` = empty), as most voxel tools expect."""
        return np.where(self.occupancy, self.color, EMPTY).astype(np.int16)

    def to_plate_codes(self) -> NDArray[np.int16]:
        """Code array resampled to plate layers (each cell repeated vertically)."""
        return np.repeat(self.to_codes(), self.plates_per_cell, axis=2)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VoxelGrid):
            return NotImplemented
        return (
            self.height_unit == other.height_unit
            and self.pitch_mm == other.pitch_mm
            and self.origin_mm == other.origin_mm
            and np.array_equal(self.occupancy, other.occupancy)
            and np.array_equal(self.color, other.color)
            and (
                np.array_equal(self.flat, other.flat, equal_nan=True)
                if self.flat is not None and other.flat is not None
                else self.flat is other.flat
            )
        )

    def __hash__(self) -> int:
        return hash((self.shape, self.height_unit, self.pitch_mm, self.filled_count))
