# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Stability checks of every intermediate state (Roadmap 3, ADR 0017)."""

from __future__ import annotations

import time

import pytest
from legolization.catalog import default_catalog
from legolization.layout import Layout

from mesh2brick.backends.checks import (
    WarmWalker,
    check_state,
    check_states,
    default_workers,
    state_ids,
)

pytestmark = pytest.mark.ldraw

RED = 4
TOWER = 40
"""1 x 1 bricks on the free end that make the cantilever tip over."""


def _cantilever() -> tuple[Layout, list[tuple[int, ...]]]:
    """Base, a 1 x 8 arm on one stud, a heavy tower on its end, a prop below.

    Steps: (1) a 1 x 1 brick on the ground, (2) a 1 x 8 brick on it with
    seven studs in the air, (3) a tower of 1 x 1 bricks on the free end,
    (4) a column of 1 x 1 bricks under the free end.
    """
    layout = Layout(catalog=default_catalog())
    base = layout.add("brick_1x1", 0, 0, 0, 0, RED).brick_id
    arm = layout.add("brick_1x8", 0, 0, 3, 0, RED).brick_id
    tower = tuple(
        layout.add("brick_1x1", 7, 0, 6 + 3 * level, 0, RED).brick_id
        for level in range(TOWER)
    )
    prop = (layout.add("brick_1x1", 7, 0, 0, 0, RED).brick_id,)
    return layout, [(base,), (arm,), tower, prop]


def test_part_on_a_checked_base_stands() -> None:
    layout, steps = _cantilever()
    for index in (0, 1):
        verdict = check_state(layout, steps, index, None)
        assert verdict.stable
        assert verdict.score < 1.0


def test_cantilever_needs_a_hand_until_it_is_propped() -> None:
    layout, steps = _cantilever()
    assert not check_state(layout, steps, 2, None).stable
    assert check_state(layout, steps, 3, None).stable


def test_a_part_nothing_holds_is_unstable_without_an_lp() -> None:
    layout, steps = _cantilever()
    floating = [steps[2][:1]]  # the first tower brick on its own, in the air
    verdict = check_state(layout, floating, 0, None)
    assert (verdict.stable, verdict.score) == (False, 1.0)


def test_states_only_grow() -> None:
    _, steps = _cantilever()
    assert state_ids(steps, 0) == frozenset(steps[0])
    assert state_ids(steps, 2) == frozenset(steps[0] + steps[1] + steps[2])


def test_walk_in_process_and_parallel_workers_agree() -> None:
    layout, steps = _cantilever()
    expected = [True, True, False, True]
    walked = check_states(layout, steps, None, workers=1)
    assert [v.stable for v in walked if v is not None] == expected
    seen: list[int] = []
    parallel = check_states(
        layout,
        steps,
        None,
        deadline=time.monotonic() + 120,
        workers=3,
        on_verdict=lambda index, _verdict: seen.append(index),
    )
    assert [v.stable if v else None for v in parallel] == expected
    assert sorted(seen) == [0, 1, 2, 3]


def test_no_time_left_leaves_every_state_unchecked() -> None:
    layout, steps = _cantilever()
    assert check_states(layout, steps, None, deadline=time.monotonic()) == [None] * 4


def test_warm_walker_matches_cold_checks() -> None:
    layout, steps = _cantilever()
    walker = WarmWalker.create(layout, None)
    assert isinstance(walker, WarmWalker)
    warm = [walker.check(step).stable for step in steps]
    cold = [check_state(layout, steps, i, None).stable for i in range(len(steps))]
    assert warm == cold


def test_workers_leave_one_core_free() -> None:
    assert 1 <= default_workers() <= 12
