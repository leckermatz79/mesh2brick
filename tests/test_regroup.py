# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Merging runs of steps (Phase 7): the only change outside proposals may make."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.helpers import make_brick

from mesh2brick.model import BrickModel, BuildStep
from mesh2brick.steps.plan import PlanStep
from mesh2brick.steps.regroup import (
    check_ranges,
    merge_problems,
    merge_ranges,
    new_step_index,
)
from mesh2brick.steps.structure import Structure


def structure_of(model: BrickModel) -> Structure:
    return Structure.from_cells({i: p.cells for i, p in enumerate(model.parts)})


def row_model(steps: tuple[BuildStep, ...] | None = None) -> BrickModel:
    """Four 2x4 bricks side by side on the table, one per step."""
    parts = tuple(make_brick("3001", 2 * i, 0, 0, i) for i in range(4))
    return BrickModel(name="row", parts=parts, steps=steps or (BuildStep(),) * 4)


def test_merge_ranges_concatenates_runs_in_order() -> None:
    plan = tuple(
        PlanStep(parts=(i,), origin=(i,), units=((i,),) if i == 2 else ())
        for i in range(5)
    )
    merged = merge_ranges(plan, [(1, 2), (3, 4)])
    assert [s.parts for s in merged] == [(0,), (1, 2), (3, 4)]
    assert [s.origin for s in merged] == [(0,), (1, 2), (3, 4)]
    assert merged[1].units == ((2,),)
    assert merge_ranges(plan, []) == plan


@pytest.mark.parametrize(
    "ranges", [[(1, 1)], [(0, 5)], [(2, 3), (1, 2)], [(1, 2), (2, 3)], [(-1, 1)]]
)
def test_invalid_ranges_are_rejected(ranges: list[tuple[int, int]]) -> None:
    with pytest.raises(ValueError, match="range"):
        check_ranges(ranges, 5)


def test_new_step_index_maps_old_steps_to_merged_ones() -> None:
    assert new_step_index([(1, 2), (4, 6)], 8) == (0, 1, 1, 2, 3, 3, 3, 4)
    assert new_step_index([], 3) == (0, 1, 2)


def test_side_by_side_steps_may_merge() -> None:
    model = row_model()
    assert merge_problems(model, structure_of(model), (0, 3), max_size=10) == ()


def test_merge_respects_size_limit_and_bounds() -> None:
    model = row_model()
    (problem,) = merge_problems(model, structure_of(model), (0, 3), max_size=3)
    assert "4 parts (at most 3)" in problem
    (problem,) = merge_problems(model, structure_of(model), (2, 4), max_size=9)
    assert "between 1 and 4" in problem


def test_merge_never_mixes_subassemblies_or_attach_steps() -> None:
    steps = (
        BuildStep(),
        BuildStep(submodel="wing"),
        BuildStep(attaches="wing"),
        BuildStep(),
    )
    model = row_model(steps)
    problems = merge_problems(model, structure_of(model), (0, 2), max_size=10)
    assert any("sub-assemblies" in p for p in problems)
    assert any("attaches" in p for p in problems)


def test_merge_must_not_hide_a_moment_that_needs_a_hand() -> None:
    model = row_model(
        (
            BuildStep(stable=True),
            BuildStep(stable=False),
            BuildStep(stable=True),
            BuildStep(stable=False),
        )
    )
    (problem,) = merge_problems(model, structure_of(model), (1, 2), max_size=10)
    assert "supporting hand after step 2" in problem
    # still needs the hand after the merged step: the hint stays true
    assert merge_problems(model, structure_of(model), (2, 3), max_size=10) == ()


def test_merge_keeps_covered_parts_visible() -> None:
    base = make_brick("3001", 0, 0, 0, 0)
    cover = make_brick("3001", 0, 0, 3, 1)  # sits exactly on the base
    side = make_brick("3001", 2, 0, 3, 2, w=1, d=1)
    model = BrickModel(
        name="stack",
        parts=(base, cover, replace(side, step=2)),
        steps=(BuildStep(),) * 3,
    )
    (problem,) = merge_problems(model, structure_of(model), (0, 1), max_size=10)
    assert "of step 1 would be mostly covered" in problem
    assert merge_problems(model, structure_of(model), (1, 2), max_size=10) == ()
