# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Hanging parts: place a part together with the part that holds it.

Layer-order steps place every part when its layer comes up. A part below an
overhang has nothing underneath at that point; it only gets held once the
part above it is placed, maybe several steps later. Following such steps,
the part would simply fall off.

:func:`attach_hanging` moves each such part into the step that places its
holder and marks both as one *unit*: put the hanging part onto the underside
of its holder in the hand, then place both together. Only steps on the main
model are rewritten; plans with subassemblies pass through unchanged
(their backend already checked them).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mesh2brick.steps.plan import PlanStep
    from mesh2brick.steps.structure import Structure


@dataclass(frozen=True, slots=True)
class HangingResult:
    """The rewritten plan and what changed.

    Attributes:
        steps: the new plan (steps that lost all their parts are dropped).
        moved: parts moved into the step of their holder.
        units: groups of parts now put together in the hand first.
        blocked: units that cannot be lowered in from above because a part
            placed earlier is in the way (they have to be pushed on from below).
        loose: parts that never get held (left where they were).
    """

    steps: tuple[PlanStep, ...]
    moved: int = 0
    units: int = 0
    blocked: int = 0
    loose: int = 0


def attach_hanging(steps: Sequence[PlanStep], structure: Structure) -> HangingResult:
    """Move hanging parts into the step of the part that holds them."""
    if not all(step.on_main_model for step in steps):
        return HangingResult(steps=tuple(steps))
    target = _holding_steps(steps, structure)
    moved_into: dict[int, list[int]] = {}
    for part, (origin, holder_step) in target.items():
        if holder_step is not None and holder_step != origin:
            moved_into.setdefault(holder_step, []).append(part)
    moving = {part for parts in moved_into.values() for part in parts}
    rewritten: list[PlanStep] = []
    placed: set[int] = set()
    units = blocked = 0
    for index, step in enumerate(steps):
        own = tuple(p for p in step.parts if p not in moving)
        arriving = tuple(sorted(moved_into.get(index, ())))
        groups = _units(own, arriving, structure)
        for group in groups:
            hanging = [p for p in group if p in arriving]
            if structure.blocked_from_above(hanging, placed):
                blocked += 1
        units += len(groups)
        parts = own + arriving
        placed.update(parts)
        if parts:
            rewritten.append(replace(step, parts=parts, units=(*step.units, *groups)))
    loose = sum(1 for _, holder in target.values() if holder is None)
    return HangingResult(
        steps=tuple(rewritten),
        moved=len(moving),
        units=units,
        blocked=blocked,
        loose=loose,
    )


def _holding_steps(
    steps: Sequence[PlanStep], structure: Structure
) -> dict[int, tuple[int, int | None]]:
    """Per part that would hang: (its step, the step that first holds it)."""
    placed: set[int] = set()
    waiting: dict[int, int] = {}
    result: dict[int, tuple[int, int | None]] = {}
    for index, step in enumerate(steps):
        candidates = placed | set(step.parts) | set(waiting)
        held = structure.grounded(candidates)
        resolved = [p for p in waiting if p in held]
        for part in resolved:
            result[part] = (waiting.pop(part), index)
        for part in step.parts:
            if part not in held:
                waiting[part] = index
        placed.update(p for p in step.parts if p in held)
        placed.update(resolved)
    for part, origin in waiting.items():
        result[part] = (origin, None)
    return result


def _units(
    own: tuple[int, ...], arriving: tuple[int, ...], structure: Structure
) -> tuple[tuple[int, ...], ...]:
    """Hanging parts plus the parts of this step they hang from, as groups."""
    if not arriving:
        return ()
    own_set = set(own)
    arriving_set = set(arriving)
    holders = {
        other
        for part in arriving
        for other in structure.neighbours(part)
        if other in own_set
    }
    groups = structure.components(arriving_set | holders)
    return tuple(tuple(sorted(group)) for group in groups if group & arriving_set)
