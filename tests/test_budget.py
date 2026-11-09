# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Choosing the step planner for the time left (Roadmap 3, ADR 0017)."""

from __future__ import annotations

import pytest

from mesh2brick.steps.budget import (
    MIN_SEQUENCING_S,
    THOROUGH_MAX_PARTS,
    THOROUGH_SHARE,
    choose_planner,
    thorough_estimate_s,
)


def test_small_model_with_time_gets_the_search() -> None:
    choice = choose_planner("auto", 153, 240.0)
    assert choice.planner == "thorough"
    assert choice.search_s == pytest.approx(THOROUGH_SHARE * 240.0)


def test_big_model_gets_checked_layers_whatever_the_time() -> None:
    for budget in (40.0, 200.0, 1100.0, None):
        assert choose_planner("auto", 873, budget).planner == "checked-layers"
    assert choose_planner("auto", THOROUGH_MAX_PARTS + 1, None).planner == (
        "checked-layers"
    )


def test_search_that_would_not_fit_is_not_started() -> None:
    parts = THOROUGH_MAX_PARTS
    budget = thorough_estimate_s(parts) / THOROUGH_SHARE - 1.0
    assert choose_planner("auto", parts, budget).planner == "checked-layers"
    assert choose_planner("auto", parts, budget + 2.0).planner == "thorough"


def test_no_deadline_means_no_search_limit() -> None:
    choice = choose_planner("auto", 12, None)
    assert (choice.planner, choice.search_s) == ("thorough", None)


@pytest.mark.parametrize("mode", ["auto", "thorough", "fast", "checked-layers"])
def test_no_time_left_means_unchecked_layers(mode: str) -> None:
    choice = choose_planner(mode, 12, MIN_SEQUENCING_S - 0.1)  # type: ignore[arg-type]
    assert choice.planner == "layers"


def test_forced_modes_are_respected() -> None:
    assert choose_planner("layers", 12, 300.0).planner == "layers"
    assert choose_planner("checked-layers", 12, 300.0).planner == "checked-layers"
    forced = choose_planner("thorough", 2308, 1000.0)
    assert (forced.planner, forced.search_s) == ("thorough", THOROUGH_SHARE * 1000.0)
    assert choose_planner("fast", 2308, None).planner == "fast"


def test_estimate_grows_with_the_square_of_the_parts() -> None:
    assert thorough_estimate_s(873) >= 392.0  # measured on the bunny
    assert thorough_estimate_s(1000) > 3 * thorough_estimate_s(500)
