# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""How much of a build plan was checked for stability (Roadmap 3, ADR 0017).

A plan is checked step by step from the bottom: either every intermediate
state has a verdict, none has (layer order without checks), or the first
steps have one and the rest do not (the time limit stopped the checks).
This module says which, in numbers a builder understands: steps and brick
layers from the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from mesh2brick.model import BrickModel

PLATES_PER_BRICK: Final = 3

CoverageKind = Literal["all", "partial", "none"]


@dataclass(frozen=True, slots=True)
class Coverage:
    """Checked intermediate states of a plan.

    Attributes:
        checked: steps whose state after the step has a stability verdict.
        total: all steps.
        layers: brick layers (from the bottom) whose parts all lie in
            checked steps.
        all_layers: brick layers of the model.
    """

    checked: int
    total: int
    layers: int = 0
    all_layers: int = 0

    @property
    def kind(self) -> CoverageKind:
        """``all``, ``partial`` or ``none``."""
        if self.checked >= self.total:
            return "all"
        return "partial" if self.checked else "none"


def coverage(model: BrickModel) -> Coverage:
    """The checked steps of ``model`` (a step is checked if ``stable`` is set)."""
    checked = sum(step.stable is not None for step in model.steps)
    layer_of = [part.layer // PLATES_PER_BRICK for part in model.parts]
    all_layers = max(layer_of, default=-1) + 1
    open_layers = {
        layer
        for part, layer in zip(model.parts, layer_of, strict=True)
        if model.steps[part.step].stable is None
    }
    layers = min(open_layers, default=all_layers)
    return Coverage(
        checked=checked, total=model.step_count, layers=layers, all_layers=all_layers
    )
