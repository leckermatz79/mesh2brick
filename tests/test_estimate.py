# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Roadmap 5: the part estimate of ``inspect`` (ADR 0019)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from mesh2brick.voxel import estimate as module
from mesh2brick.voxel.estimate import (
    FLOOR_PER_CELL,
    THIN_PER_CELL,
    TILED_RANGE,
    PartsEstimate,
    parts_estimate,
    plate_shell,
    quick_fill,
)
from mesh2brick.voxel.grid import EMPTY, VoxelGrid

if TYPE_CHECKING:
    from pathlib import Path

RED, BLUE, GREY = 4, 1, 71


def _grid(codes: np.ndarray, height_unit: str = "brick") -> VoxelGrid:
    return VoxelGrid.from_codes(codes, height_unit=height_unit)  # type: ignore[arg-type]


def _box(nx: int, ny: int, nz: int, code: int = RED) -> np.ndarray:
    return np.full((nx, ny, nz), code)


@pytest.mark.parametrize(
    ("shape", "parts"),
    [((2, 8, 1), 1), ((4, 8, 1), 2), ((1, 1, 3), 3), ((3, 3, 1), 2), ((2, 9, 2), 4)],
)
def test_quick_fill_uses_the_largest_bricks(
    shape: tuple[int, int, int], parts: int
) -> None:
    assert quick_fill(np.ones(shape, dtype=bool)) == parts


@pytest.mark.ldraw
@pytest.mark.parametrize("wall", [1, 2, 3])
@pytest.mark.parametrize("unit", ["brick", "plate"])
def test_plate_shell_is_legolizations_hollowing(
    fixtures_dir: Path, wall: int, unit: str
) -> None:
    from legolization.hollow import hollow_grid  # noqa: PLC0415

    from mesh2brick.backends.legolization import (  # noqa: PLC0415
        load_voxel_file,
        to_lego_grid,
    )

    ball = np.indices((11, 11, 9)) - np.array([5, 5, 4])[:, None, None, None]
    grids = [
        load_voxel_file(fixtures_dir / "heart.vox", height_unit=unit),  # type: ignore[arg-type]
        _grid(np.where((ball**2).sum(axis=0) <= 20, RED, EMPTY), unit),
        _grid(_box(9, 7, 8), unit),
    ]
    for grid in grids:
        lego = hollow_grid(
            to_lego_grid(grid),
            shell_studs=wall,
            shell_plates=wall * grid.plates_per_cell,
        )
        ours = plate_shell(grid, wall_thickness=wall)
        theirs = lego.codes >= 0
        assert ours.shape[2] - theirs.shape[2] in (0, 1, 2)  # topped up to slabs
        assert np.array_equal(ours[:, :, : theirs.shape[2]], theirs)
        assert not ours[:, :, theirs.shape[2] :].any()


def test_solid_slabs_become_bricks_and_partial_ones_plates() -> None:
    # 2 x 8 studs, 4 plates high: one brick plus one plate on top.
    tall = parts_estimate(_grid(_box(2, 8, 4), "plate"), hollow=False)
    assert tall.tiled == 2
    # A colour change inside the upper slab: three plates instead of a brick.
    codes = _box(2, 8, 6)
    codes[:, :, 4] = BLUE
    striped = parts_estimate(_grid(codes, "plate"), hollow=False)
    assert striped.tiled == 1 + 3


def test_one_part_per_colour() -> None:
    codes = _box(2, 8, 2)
    codes[:, 4:, :] = BLUE
    assert parts_estimate(_grid(codes), hollow=False).tiled == 4  # 2 x 4 each


def test_wide_area_one_cell_high_becomes_plates() -> None:
    estimate = parts_estimate(_grid(_box(16, 16, 1, GREY)))
    assert estimate.thin_cells == 256
    assert estimate.tiled == 0
    low, typical, high = (round(256 * rate) for rate in THIN_PER_CELL)
    assert (estimate.low, estimate.expected, estimate.high) == (low, typical, high)


def test_small_piece_one_cell_high_stays_a_brick() -> None:
    estimate = parts_estimate(_grid(_box(2, 6, 1)))
    assert (estimate.thin_cells, estimate.tiled, estimate.expected) == (0, 1, 1)


def test_table_top_on_legs_is_thin_but_the_legs_are_not() -> None:
    codes = np.full((20, 20, 7), EMPTY)
    codes[:, :, 6] = GREY
    for x, y in ((0, 0), (18, 0), (0, 18), (18, 18)):
        codes[x : x + 2, y : y + 2, :6] = GREY
    estimate = parts_estimate(_grid(codes))
    assert estimate.thin_cells == 400 - 16
    assert estimate.floor_cells == 0


def _expected_with_floor(
    estimate: PartsEstimate, rates: tuple[float, ...]
) -> list[int]:
    return [
        round(estimate.tiled * t + estimate.floor_cells * f)
        for t, f in zip((TILED_RANGE[0], 1.0, TILED_RANGE[1]), rates, strict=True)
    ]


def test_wide_hollow_floor_is_rebuilt_a_small_one_not() -> None:
    wide = parts_estimate(_grid(_box(18, 18, 10)))  # 14 x 14 studs of floor
    assert wide.floor_cells == 18 * 18 * 2
    assert wide.thin_cells == 0
    either = FLOOR_PER_CELL[0][1]  # bottom layer below 1,000 studs
    assert [wide.low, wide.expected, wide.high] == _expected_with_floor(wide, either)
    small = parts_estimate(_grid(_box(12, 12, 10)))  # 8 x 8 studs of floor
    assert small.floor_cells == 0


@pytest.mark.parametrize(("side", "band"), [(24, 0), (31, 0), (32, 1)])
def test_floor_rates_follow_the_floor_size(side: int, band: int) -> None:
    estimate = parts_estimate(_grid(_box(side, side, 10)))
    rates = FLOOR_PER_CELL[band][1]
    assert [estimate.low, estimate.expected, estimate.high] == _expected_with_floor(
        estimate, rates
    )


def test_solid_fill_has_no_weak_floor() -> None:
    estimate = parts_estimate(_grid(_box(18, 18, 10)), hollow=False)
    assert estimate.floor_cells == estimate.thin_cells == 0
    assert estimate.tiled == quick_fill(np.ones((18, 18, 10), dtype=bool))


def test_hollowing_saves_parts() -> None:
    solid = parts_estimate(_grid(_box(30, 30, 20)), hollow=False)
    hollow = parts_estimate(_grid(_box(30, 30, 20)), wall_thickness=2)
    assert hollow.tiled < solid.tiled


def test_range_brackets_the_expected_count() -> None:
    ball = np.indices((21, 21, 18)) - np.array([10, 10, 9])[:, None, None, None]
    estimate = parts_estimate(_grid(np.where((ball**2).sum(axis=0) <= 90, RED, EMPTY)))
    assert 0 < estimate.low < estimate.expected < estimate.high
    assert estimate.high / estimate.low < 2


def test_empty_grid_and_bad_wall() -> None:
    empty = parts_estimate(_grid(np.full((2, 2, 2), EMPTY)))
    assert (empty.low, empty.expected, empty.high) == (0, 0, 0)
    with pytest.raises(ValueError, match="wall_thickness"):
        parts_estimate(_grid(_box(2, 2, 2)), wall_thickness=0)


def test_huge_shells_fall_back_to_their_size(monkeypatch: pytest.MonkeyPatch) -> None:
    grid = _grid(_box(10, 10, 10))
    cells = int(plate_shell(grid, wall_thickness=2).sum()) / 3
    monkeypatch.setattr(module, "MAX_FILL_CELLS", 0)
    rough = parts_estimate(grid)
    assert rough.expected == round(cells / module.CELLS_PER_PART)
    assert rough.low < rough.expected < rough.high
