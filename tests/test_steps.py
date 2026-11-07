# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Own step passes (Phase 6): structure, hanging parts, even step sizes."""

from __future__ import annotations

import pytest
from tests.helpers import make_brick

from mesh2brick.model import BrickModel, BuildStep, ColorInfo, PlacedPart
from mesh2brick.steps.balance import merge_small_steps, split_large_steps
from mesh2brick.steps.hanging import attach_hanging
from mesh2brick.steps.metrics import hanging_parts, step_stats
from mesh2brick.steps.plan import PlanStep, plan_from_steps
from mesh2brick.steps.structure import Structure

Cell = tuple[int, int, int]


def box(x: int, y: int, z: int, *, w: int = 1, d: int = 1, h: int = 1) -> list[Cell]:
    return [(x + i, y + j, z + k) for i in range(w) for j in range(d) for k in range(h)]


# A brick on the table, a long brick on top reaching out over the edge, and a
# plate hanging under the overhang (held only by the long brick).
OVERHANG = {
    0: box(0, 0, 0, w=2, d=2, h=3),  # base brick, layers 0-2
    1: box(2, 0, 2, w=1, d=2, h=1),  # plate under the overhang, layer 2
    2: box(0, 0, 3, w=3, d=2, h=3),  # long brick on top, layers 3-5
}


def overhang_structure() -> Structure:
    return Structure.from_cells(OVERHANG)


# ------------------------------------------------------------------ structure
def test_structure_connects_parts_stacked_in_a_column() -> None:
    s = overhang_structure()
    assert s.below[2] == {0, 1}
    assert s.above[0] == {2}
    assert s.above[1] == {2}
    assert s.on_table == {0}
    assert s.neighbours(1) == {2}


def test_grounded_and_floating_follow_the_placed_set() -> None:
    s = overhang_structure()
    assert s.floating([0, 1]) == {1}
    assert s.grounded([0, 1, 2]) == {0, 1, 2}
    assert s.floating([1, 2]) == {1, 2}
    assert s.components([0, 1, 2]) == [frozenset({0, 1, 2})]
    assert s.components([0, 1]) == [frozenset({0}), frozenset({1})]


def test_nothing_connects_onto_a_tile() -> None:
    cells = {0: box(0, 0, 0), 1: box(0, 0, 1)}
    assert Structure.from_cells(cells).above[0] == {1}
    tiled = Structure.from_cells(cells, {0: "tile"})
    assert tiled.above[0] == frozenset()
    assert tiled.floating([0, 1]) == {1}


def test_structure_rejects_parts_without_cells() -> None:
    with pytest.raises(ValueError, match="at least one cell"):
        Structure.from_cells({0: []})


def test_column_helpers() -> None:
    s = Structure.from_cells(
        {0: box(0, 0, 0, w=2), 1: box(0, 0, 1), 2: box(5, 5, 0), 3: box(0, 0, 4)}
    )
    assert s.share_columns([0], [1])
    assert not s.share_columns([0], [2])
    assert s.hidden_share(0, [1]) == 0.5
    assert s.hidden_share(0, [2]) == 0.0
    assert s.blocked_from_above([1], [3])
    assert not s.blocked_from_above([3], [1])


# ------------------------------------------------------------------ hanging parts
def test_hanging_part_moves_to_its_holder_as_one_unit() -> None:
    steps = plan_from_steps(
        (((0,), None, None), ((1,), None, None), ((2,), None, None))
    )
    result = attach_hanging(steps, overhang_structure())
    assert [s.parts for s in result.steps] == [(0,), (2, 1)]
    assert result.steps[1].units == ((1, 2),)
    assert result.steps[1].origin == (2,)
    assert (result.moved, result.units, result.blocked, result.loose) == (1, 1, 0, 0)


def test_parts_that_are_never_held_stay_where_they_are() -> None:
    cells = {0: box(0, 0, 0), 1: box(4, 4, 2)}
    steps = plan_from_steps((((0,), None, None), ((1,), None, None)))
    result = attach_hanging(steps, Structure.from_cells(cells))
    assert [s.parts for s in result.steps] == [(0,), (1,)]
    assert result.loose == 1
    assert result.moved == 0


def test_blocked_units_are_counted() -> None:
    cells = {
        0: box(0, 0, 0, w=2, h=3),  # base brick
        1: box(2, 0, 2),  # plate hanging under 2
        2: box(0, 0, 3, w=3, h=3),  # its holder
        4: box(5, 0, 0, h=9),  # a tower next to it ...
        3: box(2, 0, 9, w=4),  # ... carrying a beam high above the plate
    }
    steps = plan_from_steps(
        (((0, 4, 3), None, None), ((1,), None, None), ((2,), None, None))
    )
    result = attach_hanging(steps, Structure.from_cells(cells))
    assert result.moved == 1
    assert result.blocked == 1


def test_plans_with_subassemblies_pass_through() -> None:
    steps = (
        PlanStep(parts=(1,), submodel="a"),
        PlanStep(parts=(), attaches="a"),
        PlanStep(parts=(0, 2)),
    )
    result = attach_hanging(steps, overhang_structure())
    assert result.steps == steps


# ------------------------------------------------------------------ step sizes
def row_structure(count: int) -> Structure:
    """``count`` 1 x 1 bricks in a row on the table, none touching."""
    return Structure.from_cells({i: box(2 * i, 0, 0, h=3) for i in range(count)})


def test_small_steps_merge_into_a_neighbour() -> None:
    steps = plan_from_steps(
        (((0, 1, 2, 3), None, None), ((4,), None, None), ((5, 6, 7, 8), None, None))
    )
    merged = merge_small_steps(steps, row_structure(9), min_size=3, max_size=6)
    assert [s.parts for s in merged] == [(0, 1, 2, 3, 4), (5, 6, 7, 8)]
    assert merged[0].origin == (0, 1)


def test_merging_respects_the_size_limit() -> None:
    steps = plan_from_steps((((0, 1, 2), None, None), ((3,), None, None)))
    assert len(merge_small_steps(steps, row_structure(4), min_size=2, max_size=3)) == 2


def test_merging_keeps_covered_parts_in_their_own_step() -> None:
    cells = {0: box(0, 0, 0, w=2), 1: box(0, 0, 1, w=2), 2: box(1, 0, 2)}
    structure = Structure.from_cells(cells)
    covered = plan_from_steps((((0,), None, None), ((1,), None, None)))
    assert len(merge_small_steps(covered, structure, min_size=3, max_size=9)) == 2
    half = plan_from_steps((((1,), None, None), ((2,), None, None)))
    assert len(merge_small_steps(half, structure, min_size=3, max_size=9)) == 1


def test_merging_never_crosses_subassemblies_or_attach_steps() -> None:
    structure = row_structure(4)
    steps = (
        PlanStep(parts=(0,), submodel="a", origin=(0,)),
        PlanStep(parts=(1,), submodel="b", origin=(1,)),
        PlanStep(parts=(), attaches="b", origin=(2,)),
        PlanStep(parts=(2,), origin=(3,)),
    )
    assert merge_small_steps(steps, structure, min_size=3, max_size=9) == steps


def test_merge_rejects_inconsistent_sizes() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        merge_small_steps((), row_structure(1), min_size=5, max_size=4)


def test_large_steps_are_split_without_breaking_units() -> None:
    step = PlanStep(parts=tuple(range(12)), origin=(0,), units=((4, 5),))
    cells = {i: box(2 * i, 0, 0, h=3) for i in range(12)}
    cells[5] = box(8, 0, 3)  # sits on part 4
    split = split_large_steps(
        (step,), Structure.from_cells(cells), target=5, max_size=8
    )
    assert len(split) == 3
    assert sorted(p for s in split for p in s.parts) == list(range(12))
    assert all(len(s.parts) <= 8 for s in split)
    holding = [s for s in split if 4 in s.parts]
    assert 5 in holding[0].parts
    assert holding[0].units == ((4, 5),)
    assert all(s.origin == (0,) for s in split)


def test_split_leaves_small_and_subassembly_steps_alone() -> None:
    structure = row_structure(12)
    small = PlanStep(parts=(0, 1))
    sub = PlanStep(parts=tuple(range(2, 12)), submodel="a")
    assert split_large_steps((small, sub), structure, target=3, max_size=4) == (
        small,
        sub,
    )
    with pytest.raises(ValueError, match="target"):
        split_large_steps((), structure, target=0, max_size=4)


# ------------------------------------------------------------------ metrics
def part(cells: list[Cell], step: int, unit: int | None = None) -> PlacedPart:
    x, y, z = min(cells)
    return PlacedPart(
        part="3005", color=4, x=x, y=y, layer=z, yaw=0, cells=tuple(cells),
        step=step, unit=unit,
    )  # fmt: skip


def test_step_stats_count_hanging_parts_and_units() -> None:
    hanging = BrickModel(
        name="h",
        parts=(part(OVERHANG[0], 0), part(OVERHANG[1], 1), part(OVERHANG[2], 2)),
        steps=(BuildStep(),) * 3,
        colors={4: ColorInfo("Red", "#c91a09")},
    )
    assert hanging_parts(hanging) == {1}
    held = BrickModel(
        name="h",
        parts=(part(OVERHANG[0], 0), part(OVERHANG[1], 1, 1), part(OVERHANG[2], 1, 1)),
        steps=(BuildStep(),) * 2,
    )
    stats = step_stats(held)
    assert stats.hanging == 0
    assert stats.units == 1
    assert (stats.smallest, stats.largest, stats.small_steps) == (1, 2, 2)


def test_step_stats_walk_subassemblies_as_a_whole(sample_model: BrickModel) -> None:
    sub = BrickModel(
        name="s",
        parts=(
            make_brick("3001", 0, 0, 0, 0),
            make_brick("3003", 1, 1, 3, 1, w=2, d=2),
        ),
        steps=(BuildStep(), BuildStep(submodel="top"), BuildStep(attaches="top")),
    )
    assert hanging_parts(sub) == frozenset()
    assert step_stats(sample_model).steps == 2
    with pytest.raises(ValueError, match="empty"):
        step_stats(BrickModel(name="e", parts=(), steps=()))
