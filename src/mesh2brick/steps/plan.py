# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""A backend-neutral build plan that mesh2brick's own step passes rewrite.

Backends translate their step plan into a tuple of :class:`PlanStep` (part
ids are whatever ids the backend uses), run the passes of this package and
translate the result back. ``origin`` keeps track of the backend steps a
rewritten step came from, so per-step backend data (stability verdicts,
view hints) can be carried over.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One build step of a plan.

    Attributes:
        parts: part ids placed in this step, in placement order.
        submodel: subassembly built in this step (``None``: main model).
        attaches: subassembly seated onto the main model in this step.
        origin: indices of the original backend steps merged into this one.
        units: groups of ``parts`` that are put together in the hand first
            and then placed as one piece.
    """

    parts: tuple[int, ...]
    submodel: str | None = None
    attaches: str | None = None
    origin: tuple[int, ...] = ()
    units: tuple[tuple[int, ...], ...] = ()

    @property
    def on_main_model(self) -> bool:
        """Places individual parts on the main model (not a sub or attach step)."""
        return self.submodel is None and self.attaches is None


def plan_from_steps(
    steps: tuple[tuple[tuple[int, ...], str | None, str | None], ...],
) -> tuple[PlanStep, ...]:
    """Build a plan from ``(parts, submodel, attaches)`` triples, one per step."""
    return tuple(
        PlanStep(parts=parts, submodel=submodel, attaches=attaches, origin=(index,))
        for index, (parts, submodel, attaches) in enumerate(steps)
    )
