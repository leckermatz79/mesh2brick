# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Phase 5: parts LEGO does not make in a colour (split after / exclude before)."""

from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from mesh2brick.backends.legolization import (
    LegolizationBackend,
    restricted_catalog,
    split_unavailable,
    unavailable_parts,
)
from mesh2brick.config import load_settings
from mesh2brick.place.split import choose_split, joints, split_options
from mesh2brick.voxel.grid import VoxelGrid

GREEN = 10  # Bright Green


# ------------------------------------------------------------------ arithmetic
def test_split_options_are_minimal() -> None:
    assert split_options(8, [1, 2, 3, 4, 6]) == [(2, 6), (4, 4), (6, 2)]
    assert split_options(5, [2]) == []
    assert split_options(0, [1]) == []
    assert split_options(3, [1, 2, 3, 4]) == [(3,)]
    assert joints((2, 4, 2)) == (2, 6)


def test_choose_split_keeps_the_bond() -> None:
    lengths = [1, 2, 3, 4, 6]
    assert choose_split(8, lengths) == (4, 4)
    assert choose_split(8, lengths, avoid={4}) in {(2, 6), (6, 2)}
    assert choose_split(8, lengths, avoid={2, 4, 6}) == (4, 4)  # all clash: balanced
    assert choose_split(6, [4], avoid=()) is None


# ------------------------------------------------------------------ layouts
def _layout_with(*bricks: tuple[str, int, int, int, int, int]):  # type: ignore[no-untyped-def]
    from legolization.layout import Layout  # noqa: PLC0415

    layout = Layout(catalog=restricted_catalog(frozenset(_ALL)))
    for key, x, y, layer, yaw, colour in bricks:
        layout.add(key, x, y, layer, yaw, colour)
    return layout


_ALL = (
    "3005", "3004", "3622", "3010", "3009", "3008", "3003", "3002", "3001",
    "2456", "3007", "3024", "3023", "3710",
)  # fmt: skip


def _missing(*pairs: tuple[str, int]):  # type: ignore[no-untyped-def]
    absent = set(pairs)
    return lambda part, colour: (part, colour) not in absent


def test_split_replaces_exactly_the_same_cells() -> None:
    layout = _layout_with(
        ("brick_1x8", 0, 0, 0, 0, GREEN), ("brick_2x8", 0, 2, 3, 90, GREEN)
    )
    cells_before = set(layout.occupancy)
    report = split_unavailable(layout, _missing(("3008", GREEN), ("3007", GREEN)))
    assert (report.replaced, report.added, report.unresolved) == (2, 4, ())
    assert set(layout.occupancy) == cells_before
    parts = Counter(layout.part_of(b).ldraw_part for b in layout)
    assert parts == {"3010": 2, "3001": 2}  # 1x8 -> 2x 1x4, 2x8 -> 2x 2x4
    assert {b.colour_code for b in layout} == {GREEN}


def test_split_staggers_joints_against_the_layer_below() -> None:
    layout = _layout_with(
        ("brick_1x4", 0, 0, 0, 0, 4),
        ("brick_1x4", 4, 0, 0, 0, 4),  # joint at x = 4 below
        ("brick_1x8", 0, 0, 3, 0, GREEN),
    )
    split_unavailable(layout, _missing(("3008", GREEN)))
    top = sorted(
        (min(c[0] for c in layout.cells_of(b)), layout.part_of(b).ldraw_part)
        for b in layout
        if b.layer == 3
    )
    assert [x for x, _ in top] in ([0, 2], [0, 6])  # 2 + 6 or 6 + 2, not 4 + 4


def test_split_falls_back_to_rows_and_reports_failures() -> None:
    layout = _layout_with(("brick_2x8", 0, 0, 0, 0, GREEN))
    # No 2-wide part exists in green: two 1-wide rows (1x8 exists in green here).
    missing = _missing(
        ("3007", GREEN),
        ("2456", GREEN),
        ("3001", GREEN),
        ("3002", GREEN),
        ("3003", GREEN),
    )
    report = split_unavailable(layout, missing)
    assert report.replaced == 1
    assert Counter(layout.part_of(b).ldraw_part for b in layout) == {"3008": 2}
    stuck = _layout_with(("plate_1x4", 0, 0, 0, 0, GREEN))
    nothing = _missing(*((p, GREEN) for p in ("3710", "3623", "3023", "3024")))
    report = split_unavailable(stuck, nothing)
    assert report.unresolved == (("3710", GREEN),)
    assert len(stuck) == 1  # left as it was


def test_unavailable_parts_for_exclusion() -> None:
    settings = load_settings(None, [])
    gone = unavailable_parts(
        [GREEN, 4], settings, _missing(("3008", GREEN), ("3005", GREEN))
    )
    assert gone == {"3008"}  # the 1x1 filler cannot go
    slopes = load_settings(None, ["parts.categories=[brick, plate, slope]"])
    gone = unavailable_parts([GREEN], slopes, _missing(("3039", GREEN)))
    assert {"3039", "3040b", "4286"} <= gone  # all slopes or none
    no_slopes = load_settings(None, ["parts.categories=[brick, plate]"])
    assert unavailable_parts([GREEN], no_slopes, _missing(("3039", GREEN))) == set()


@pytest.mark.ldraw
@pytest.mark.parametrize("mode", ["report", "split", "exclude"])
def test_modes_end_to_end(mode: str) -> None:
    """A green wall 16 studs long: LEGO makes no 1x8 brick in this colour?"""
    occupancy = np.zeros((16, 1, 3), dtype=bool)
    occupancy[:, 0, :] = True
    grid = VoxelGrid(
        occupancy=occupancy,
        color=np.where(occupancy, GREEN, -1).astype(np.int32),
        height_unit="brick",
        pitch_mm=8.0,
        origin_mm=(0.0, 0.0, 0.0),
    )
    settings = load_settings(
        None,
        [f"parts.availability={mode}", "steps.sequencing=layers", "voxel.fill=solid"],
    )
    placement = LegolizationBackend().place(grid, settings, name="wall")
    from mesh2brick.export.bom import build_bom  # noqa: PLC0415

    bom = build_bom(placement.model)
    assert bom.total == placement.model.part_count
    if mode != "report":
        assert not bom.not_produced()
    assert placement.stability.component_count == 1


def test_non_rectangular_parts_are_left_alone() -> None:
    layout = _layout_with(("brick_corner_2x2", 0, 0, 0, 0, GREEN))
    report = split_unavailable(layout, _missing(("2357", GREEN)))
    assert report.unresolved == (("2357", GREEN),)
    assert len(layout) == 1


def test_failed_replacement_is_rolled_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import mesh2brick.backends.legolization as backend  # noqa: PLC0415

    real = backend._place_exact
    calls: list[str] = []

    def second_fails(layout, key, target, layer, colour):  # type: ignore[no-untyped-def]
        calls.append(key)
        return None if len(calls) == 2 else real(layout, key, target, layer, colour)

    monkeypatch.setattr(backend, "_place_exact", second_fails)
    layout = _layout_with(("brick_1x8", 0, 0, 0, 0, GREEN))
    before = {(b.part_key, b.x, b.y, b.layer, b.yaw) for b in layout}
    report = split_unavailable(layout, _missing(("3008", GREEN)))
    assert report.unresolved == (("3008", GREEN),)
    assert {(b.part_key, b.x, b.y, b.layer, b.yaw) for b in layout} == before


def test_stacked_joints_measures_the_bond() -> None:
    from mesh2brick.backends.legolization import stacked_joints  # noqa: PLC0415

    stacked = _layout_with(
        ("brick_1x4", 0, 0, 0, 0, 4), ("brick_1x4", 4, 0, 0, 0, 4),
        ("brick_1x4", 0, 0, 3, 0, 4), ("brick_1x4", 4, 0, 3, 0, 4),
    )  # fmt: skip
    assert stacked_joints(stacked) == (1, 1)  # joint at x = 4 runs straight up
    bonded = _layout_with(
        ("brick_1x4", 0, 0, 0, 0, 4), ("brick_1x4", 4, 0, 0, 0, 4),
        ("brick_1x2", 0, 0, 3, 0, 4), ("brick_1x4", 2, 0, 3, 0, 4), ("brick_1x2", 6, 0, 3, 0, 4),
    )  # fmt: skip
    assert stacked_joints(bonded) == (0, 1)
