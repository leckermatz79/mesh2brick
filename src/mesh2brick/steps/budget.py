# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Which step planner fits the time left (Roadmap 3, ADR 0017).

Two planners give stability-checked steps:

* **thorough**: legolization's own search for a stable order, with
  sub-assemblies. Its time grows with the square of the part count
  (docs/benchmarks.md: 34-100 s at about 600 parts, 392 s for the bunny's
  873); on big hollow models it leaves many steps that need a hand.
* **checked layers**: mesh2brick's layer order with parts under overhangs
  pre-assembled (Phase 6), every intermediate state checked afterwards, in
  parallel. On every fixture it needed a hand in no step at all and took a
  fraction of the search's time (docs/benchmarks.md).

``auto`` keeps the search for models up to :data:`THOROUGH_MAX_PARTS`, as in
1.3 (its sub-assemblies and order are what small models' instructions look
like), when its estimated time fits the budget, and takes checked layers
otherwise; whether every state of the checked layers gets checked is then up
to the budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

Planner = Literal["thorough", "fast", "checked-layers", "layers"]
Mode = Literal["auto", "thorough", "fast", "checked-layers", "layers"]

THOROUGH_MAX_PARTS: Final = 500
"""``auto`` uses legolization's search up to this size, as in 1.3; above it the
search does not fit a 5-minute conversion and its plans need a hand often."""
THOROUGH_S_PER_PART_SQ: Final = 5.2e-4
"""Upper bound of legolization's search time per squared part count (bunny:
392 s for 873 parts; most models need less)."""
THOROUGH_BASE_S: Final = 2.0
"""Fixed cost of the search (child process start, chunking)."""
THOROUGH_SHARE: Final = 0.75
"""Share of the time left that the search may use; the rest is kept for the
checked layer order if the search does not finish."""
MIN_SEQUENCING_S: Final = 5.0
"""Below this, steps follow layer order without checks."""
LLM_RESERVE_S: Final = 60.0
"""Time the step checks leave for the optional LLM layer (it needed about
50 s on Duo, Phase 7)."""


@dataclass(frozen=True, slots=True)
class Choice:
    """The planner for one model and the time it may take.

    Attributes:
        planner: what plans the steps.
        search_s: time limit for legolization's search (``thorough`` and
            ``fast``; ``None``: no limit); afterwards the checked layer order
            takes over.
        reason: why, in a few words (for notes and tests).
    """

    planner: Planner
    search_s: float | None = None
    reason: str = ""


def thorough_estimate_s(parts: int) -> float:
    """Pessimistic time of legolization's search for ``parts`` parts."""
    return THOROUGH_BASE_S + THOROUGH_S_PER_PART_SQ * parts * parts


def choose_planner(mode: Mode, parts: int, budget_s: float | None) -> Choice:
    """The planner for ``mode``, a model of ``parts`` and ``budget_s`` seconds.

    ``budget_s`` is the time left for planning and checking steps (``None``:
    no time limit).
    """
    share = None if budget_s is None else THOROUGH_SHARE * budget_s
    if mode == "layers" or (budget_s is not None and budget_s < MIN_SEQUENCING_S):
        return Choice(
            "layers", reason="requested" if mode == "layers" else "no time left"
        )
    if mode != "auto":
        search = share if mode in ("thorough", "fast") else None
        return Choice(mode, search_s=search, reason="requested")
    if parts > THOROUGH_MAX_PARTS:
        return Choice("checked-layers", reason="big model")
    if share is not None and thorough_estimate_s(parts) > share:
        return Choice("checked-layers", reason="search would not fit the time left")
    return Choice("thorough", search_s=share, reason="small model")
