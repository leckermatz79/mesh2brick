# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""How much of a plan was checked for stability (Roadmap 3)."""

from __future__ import annotations

from tests.helpers import make_brick

from mesh2brick.model import BrickModel, BuildStep
from mesh2brick.steps.coverage import coverage


def _tower(verdicts: list[bool | None]) -> BrickModel:
    """One 2 x 4 brick per step, stacked; step i at brick layer i."""
    parts = tuple(make_brick("3001", 0, 0, 3 * i, i) for i in range(len(verdicts)))
    return BrickModel(
        name="tower", parts=parts, steps=tuple(BuildStep(stable=v) for v in verdicts)
    )


def test_every_step_checked() -> None:
    result = coverage(_tower([True, False, True]))
    assert (result.kind, result.checked, result.total) == ("all", 3, 3)
    assert (result.layers, result.all_layers) == (3, 3)


def test_nothing_checked() -> None:
    result = coverage(_tower([None, None]))
    assert (result.kind, result.checked, result.layers, result.all_layers) == (
        "none",
        0,
        0,
        2,
    )


def test_bottom_checked_top_open() -> None:
    result = coverage(_tower([True, True, None, None, True]))
    assert (result.kind, result.checked, result.total) == ("partial", 3, 5)
    assert (result.layers, result.all_layers) == (2, 5)
