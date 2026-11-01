# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
from __future__ import annotations

import numpy as np
import pytest

from mesh2brick.voxel.grid import EMPTY, VoxelGrid


def _codes() -> np.ndarray:
    codes = np.full((3, 2, 2), EMPTY, dtype=np.int16)
    codes[0, 0, 0] = 4
    codes[1, 0, 0] = 4
    codes[2, 1, 1] = 15
    return codes


def test_from_codes_round_trip() -> None:
    grid = VoxelGrid.from_codes(_codes())
    assert grid.shape == (3, 2, 2)
    assert grid.filled_count == 3
    assert grid.colors_used == (4, 15)
    np.testing.assert_array_equal(grid.to_codes(), _codes())


def test_arrays_are_read_only_copies() -> None:
    codes = _codes()
    grid = VoxelGrid.from_codes(codes)
    codes[0, 0, 0] = 1
    assert grid.color[0, 0, 0] == 4
    with pytest.raises(ValueError, match="read-only"):
        grid.occupancy[0, 0, 0] = False


@pytest.mark.parametrize(
    ("unit", "plates", "height_mm"),
    [("brick", 3, 9.6), ("plate", 1, 3.2)],
)
def test_cell_size(unit: str, plates: int, height_mm: float) -> None:
    grid = VoxelGrid.from_codes(_codes(), height_unit=unit)  # type: ignore[arg-type]
    assert grid.plates_per_cell == plates
    assert grid.cell_size_mm == pytest.approx((8.0, 8.0, height_mm))


def test_to_plate_codes_repeats_layers() -> None:
    grid = VoxelGrid.from_codes(_codes(), height_unit="brick")
    plates = grid.to_plate_codes()
    assert plates.shape == (3, 2, 6)
    assert (plates[0, 0, 0:3] == 4).all()
    assert (plates[2, 1, 3:6] == 15).all()


def test_equality_compares_content_and_metadata() -> None:
    a = VoxelGrid.from_codes(_codes())
    assert a == VoxelGrid.from_codes(_codes())
    assert a != VoxelGrid.from_codes(_codes(), height_unit="plate")
    assert a != VoxelGrid.from_codes(_codes(), pitch_mm=4.0)
    assert hash(a) == hash(VoxelGrid.from_codes(_codes()))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"occupancy": np.zeros((2, 2), bool)}, "3-D"),
        ({"occupancy": np.zeros((2, 2, 2), np.int8)}, "boolean"),
        ({"color": np.full((2, 2, 3), -1, np.int32)}, "shape"),
        ({"color": np.full((2, 2, 2), -1.0)}, "integer"),
        ({"pitch_mm": 0.0}, "pitch_mm"),
        ({"height_unit": "duplo"}, "height_unit"),
    ],
)
def test_validation(kwargs: dict[str, object], message: str) -> None:
    args: dict[str, object] = {
        "occupancy": np.zeros((2, 2, 2), bool),
        "color": np.full((2, 2, 2), EMPTY, np.int32),
    }
    args.update(kwargs)
    with pytest.raises(ValueError, match=message):
        VoxelGrid(**args)  # type: ignore[arg-type]


def test_colour_must_match_occupancy() -> None:
    occupancy = np.zeros((1, 1, 1), bool)
    with pytest.raises(ValueError, match="EMPTY"):
        VoxelGrid(occupancy=occupancy, color=np.full((1, 1, 1), 4, np.int32))
    with pytest.raises(ValueError, match="non-negative"):
        VoxelGrid(occupancy=~occupancy, color=np.full((1, 1, 1), EMPTY, np.int32))
