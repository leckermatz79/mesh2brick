# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Merge runs of consecutive build steps, and check whether a merge is safe.

This is how outside proposals (Phase 7: the LLM layer) may change a step
plan: they name runs of consecutive steps to build as one step, and nothing
else. A merge never changes the order of parts, so the model after each new
step is exactly the model after some original step: no part can end up
hanging in the air, and that step's stability verdict still holds.

:func:`merge_problems` refuses a run when

* it mixes the main model with a subassembly (or two subassemblies), or
  contains a step that seats a subassembly,
* it would have more than ``max_size`` parts,
* the model needs a supporting hand after one of its steps but not after
  the last one (the merged step would hide that moment), or
* a part of an earlier step gets more than half of its stud columns covered
  by later parts of the run (it could not be seen in the step picture).

Ranges are 0-based and inclusive: ``(2, 4)`` merges the third to fifth step.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Final

from mesh2brick.steps.balance import MAX_HIDDEN_SHARE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mesh2brick.model import BrickModel
    from mesh2brick.steps.plan import PlanStep
    from mesh2brick.steps.structure import Structure

Range = tuple[int, int]
MIN_RUN: Final = 2


def check_ranges(ranges: Sequence[Range], step_count: int) -> None:
    """Raise if ``ranges`` are not ordered, disjoint runs of existing steps.

    Raises:
        ValueError: naming the first bad range.
    """
    previous = -1
    for first, last in ranges:
        if not 0 <= first < last < step_count:
            msg = (
                f"range {(first, last)} is not a run of 2+ steps in 0..{step_count - 1}"
            )
            raise ValueError(msg)
        if first <= previous:
            msg = f"range {(first, last)} overlaps or precedes the range before it"
            raise ValueError(msg)
        previous = last


def merge_ranges(
    steps: Sequence[PlanStep], ranges: Sequence[Range]
) -> tuple[PlanStep, ...]:
    """The plan with every run in ``ranges`` built as one step.

    Parts, origins and pre-assembly units are concatenated in order; the
    merged step keeps the first step's submodel/attach markers (runs that
    mix them are rejected by :func:`merge_problems` before this is called).

    Raises:
        ValueError: if ``ranges`` are invalid (see :func:`check_ranges`).
    """
    check_ranges(ranges, len(steps))
    start = dict(ranges)
    merged: list[PlanStep] = []
    index = 0
    while index < len(steps):
        last = start.get(index, index)
        run = steps[index : last + 1]
        merged.append(
            replace(
                run[0],
                parts=tuple(p for s in run for p in s.parts),
                origin=tuple(o for s in run for o in s.origin),
                units=tuple(u for s in run for u in s.units),
            )
        )
        index = last + 1
    return tuple(merged)


def new_step_index(ranges: Sequence[Range], step_count: int) -> tuple[int, ...]:
    """For each original step, the index of the step it ends up in.

    Raises:
        ValueError: if ``ranges`` are invalid (see :func:`check_ranges`).
    """
    check_ranges(ranges, step_count)
    start = dict(ranges)
    mapping: list[int] = []
    index = new = 0
    while index < step_count:
        last = start.get(index, index)
        mapping.extend([new] * (last - index + 1))
        index, new = last + 1, new + 1
    return tuple(mapping)


def merge_problems(
    model: BrickModel,
    structure: Structure,
    run: Range,
    *,
    max_size: int,
) -> tuple[str, ...]:
    """Why the steps ``run`` of ``model`` must not be merged (empty: they may).

    ``structure`` holds the stud connections of ``model.parts`` keyed by
    part index. Messages use 1-based step numbers, as builders count.
    """
    first, last = run
    if not 0 <= first < last < model.step_count:
        message = (
            f"steps {first + 1}-{last + 1} are not a run of at least {MIN_RUN} "
            f"steps between 1 and {model.step_count}"
        )
        return (message,)
    steps = model.steps[first : last + 1]
    problems: list[str] = []
    if len({s.submodel for s in steps}) > 1:
        problems.append("the run mixes the main model and sub-assemblies")
    if any(s.attaches is not None for s in steps):
        problems.append("the run contains a step that attaches a sub-assembly")
    members = [
        [i for i, p in enumerate(model.parts) if p.step == step]
        for step in range(first, last + 1)
    ]
    size = sum(len(m) for m in members)
    if size > max_size:
        problems.append(f"the merged step would have {size} parts (at most {max_size})")
    if steps[-1].stable is not False:
        held = [first + i + 1 for i, s in enumerate(steps[:-1]) if s.stable is False]
        if held:
            problems.append(
                f"the model needs a supporting hand after step {held[0]}; merging "
                "would hide that moment"
            )
    for offset, own in enumerate(members[:-1]):
        later = [p for m in members[offset + 1 :] for p in m]
        covered = [
            p for p in own if structure.hidden_share(p, later) > MAX_HIDDEN_SHARE
        ]
        if covered:
            problems.append(
                f"{len(covered)} part(s) of step {first + offset + 1} would be "
                "mostly covered by later parts of the same step"
            )
    return tuple(problems)
