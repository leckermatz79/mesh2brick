# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Measures of instruction quality on a finished :class:`BrickModel`."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mesh2brick.steps.structure import Structure

if TYPE_CHECKING:
    from mesh2brick.model import BrickModel


@dataclass(frozen=True, slots=True)
class StepStats:
    """Step sizes and hanging parts of a model's instructions.

    Attributes:
        steps: all build steps (including subassembly and attach steps).
        smallest, median, largest: parts per step, over steps that place parts.
        small_steps: steps with fewer than ``small_below`` parts.
        small_below: the threshold used for ``small_steps``.
        hanging: main-model parts that hang in the air for at least one step
            (nothing holds them yet when the step is done).
        units: groups of parts put together in the hand before placing.
    """

    steps: int
    smallest: int
    median: float
    largest: int
    small_steps: int
    small_below: int
    hanging: int
    units: int


def step_stats(model: BrickModel, *, small_below: int = 3) -> StepStats:
    """Measure step sizes and hanging parts of ``model``.

    Raises:
        ValueError: for a model without parts.
    """
    if not model.parts:
        msg = "an empty model has no steps to measure"
        raise ValueError(msg)
    sizes = [len(model.parts_in_step(s)) for s in range(model.step_count)]
    placing = [size for size in sizes if size]
    units = {(p.step, p.unit) for p in model.parts if p.unit is not None}
    return StepStats(
        steps=model.step_count,
        smallest=min(placing),
        median=float(statistics.median(placing)),
        largest=max(placing),
        small_steps=sum(1 for size in placing if size < small_below),
        small_below=small_below,
        hanging=len(hanging_parts(model)),
        units=len(units),
    )


def hanging_parts(model: BrickModel) -> frozenset[int]:
    """Indices of main-model parts that hang in the air after some step.

    Subassemblies are seated as a whole at their attach step; their own
    build on the table is not walked.
    """
    structure = Structure.from_cells(
        {i: p.cells for i, p in enumerate(model.parts)},
        {i: p.category for i, p in enumerate(model.parts)},
    )
    steps = model.steps
    members: dict[str, list[int]] = {}
    for i, part in enumerate(model.parts):
        sub = steps[part.step].submodel
        if sub is not None:
            members.setdefault(sub, []).append(i)
    by_step: dict[int, list[int]] = {}
    for i, part in enumerate(model.parts):
        if steps[part.step].submodel is None:
            by_step.setdefault(part.step, []).append(i)
    placed: set[int] = set()
    hanging: set[int] = set()
    for index, step in enumerate(steps):
        if step.submodel is not None:
            continue
        placed.update(by_step.get(index, ()))
        if step.attaches is not None:
            placed.update(members.get(step.attaches, ()))
        hanging |= structure.floating(placed)
    return frozenset(hanging)
