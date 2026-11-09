# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Stability checks of every intermediate state, in parallel (ADR 0017).

The states of a build plan only grow: the model after step 1, after step 2,
and so on. Each is judged by legolization's rigid-block-equilibrium LP, the
same model legolization's planner uses. Two kinds of workers share the work
and meet in the middle:

* one **walker** checks the states bottom-up with one LP model that grows
  with the plan and is re-solved warm (legolization's ``PrefixSolver``, with
  a time limit per solve and the primal simplex). Small and simply stacked
  states cost milliseconds this way;
* the other workers check the states **top-down**, each with an LP solved
  from scratch ("cold"). Big states of hollow models cost thousands of
  simplex iterations warm, and a warm solve that runs out of time leaves a
  bad start for the next one; cold, they are independent of each other.

A state with a part that no stud connection links to the ground is unstable
without an LP (legolization's own "floating" shortcut). When the time is up
all workers are terminated (a hard stop, as for placement in ADR 0015); the
states checked so far keep their verdict, the others stay unchecked.
"""

from __future__ import annotations

import math
import multiprocessing
import os
import queue
import time
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING, Any, Final

import highspy
from legolization.catalog import default_catalog
from legolization.graph import ConnectionGraph
from legolization.layout import Layout
from legolization.stability.prefix import PrefixSolver
from legolization.stability.solver import SolverConfig, analyze

from mesh2brick.backends.protocols import BackendError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from multiprocessing.sharedctypes import SynchronizedArray


MAX_WORKERS: Final = 12
"""Upper bound for worker processes. On the 12-core M2 Max, 11 workers were
10-13 % faster than 8 (toadstool 119 -> 104 s, sphere 196 -> 176 s); the gain
flattens with the slower efficiency cores."""
WARM_LP_TIME_LIMIT_S: Final = 5.0
"""Wall-clock limit per warm solve; a slower one is solved cold instead.
Without it a warm simplex can stall for minutes (measured on the torus)."""
POLL_S: Final = 1.0
"""How often the parent looks whether its workers are still alive."""
PRIMAL_SIMPLEX: Final = 4
"""HiGHS ``simplex_strategy`` for the warm solves: primal (a third faster
than dual after appending a step, measured on the bunny)."""


@dataclass(frozen=True, slots=True)
class Verdict:
    """Stability of the model after one step."""

    stable: bool
    score: float
    """legolization's worst per-part score (1: a part falls or slips)."""


def default_workers() -> int:
    """Worker processes for this machine: all cores but one, at most 12."""
    return max(1, min(MAX_WORKERS, (os.cpu_count() or 2) - 1))


def state_ids(steps: Sequence[Sequence[int]], index: int) -> frozenset[int]:
    """Part ids of the model after step ``index`` (0-based)."""
    return frozenset(part for step in steps[: index + 1] for part in step)


def check_state(
    layout: Layout,
    steps: Sequence[Sequence[int]],
    index: int,
    config: SolverConfig | None,
) -> Verdict:
    """Check the model after step ``index`` on its own (one cold LP at most)."""
    state = layout.subset(state_ids(steps, index))
    if ConnectionGraph.from_layout(state).floating_ids():
        return Verdict(stable=False, score=1.0)
    result = analyze(state, config)
    return Verdict(stable=result.stable, score=float(result.max_score))


class _PerRunLimitHighs(highspy.Highs):
    """``Highs`` whose every ``run()`` gets its own wall-clock limit."""

    limit_s: float = WARM_LP_TIME_LIMIT_S

    def run(self) -> highspy.HighsStatus:
        """Run with ``limit_s`` seconds from now."""
        self.setOptionValue("time_limit", self.getRunTime() + self.limit_s)
        status: highspy.HighsStatus = super().run()
        return status


class WarmWalker(PrefixSolver):
    """legolization's warm prefix solver with a time limit per solve.

    ``PrefixSolver`` (legolization 0.5.0) gives its HiGHS instance no time
    limit; after a large or awkward step the warm simplex can stall for
    minutes. Here every solve gets :data:`WARM_LP_TIME_LIMIT_S` and uses the
    primal simplex; a solve that does not finish falls back to
    legolization's cold path (the 1.3 attempt order), as any failed warm
    solve does.
    """

    def __init__(self, layout: Layout, config: SolverConfig) -> None:
        """Build the warm model with a limited HiGHS instance."""
        super().__init__(layout, config)
        highs = _PerRunLimitHighs()  # type: ignore[no-untyped-call]
        for name, value in (
            ("output_flag", False),
            ("presolve", "off"),
            ("solver", "simplex"),
            ("threads", 1),
            ("simplex_strategy", PRIMAL_SIMPLEX),
        ):
            highs.setOptionValue(name, value)
        self._h = highs  # no rows yet: legolization adds them lazily

    def check(self, step: Sequence[int]) -> Verdict:
        """Add ``step`` to the model and return the new state's verdict."""
        chunk = tuple(step)
        result = self.probe(chunk)
        self.commit(chunk)
        return Verdict(stable=result.stable, score=float(result.max_score))


def _check_prefix_solver() -> None:
    """Fail early if legolization's ``PrefixSolver`` changed.

    :class:`WarmWalker` replaces its HiGHS instance ``_h`` while it is empty.
    """
    solver = PrefixSolver(Layout(catalog=default_catalog()), SolverConfig())
    highs = getattr(solver, "_h", None)
    if not isinstance(highs, highspy.Highs) or highs.getNumRow():
        msg = (
            f"legolization {version('legolization')}: PrefixSolver changed; revisit "
            "WarmWalker in backends/checks.py (docs/UPSTREAM.md, local patch #16)"
        )
        raise BackendError(msg)


_check_prefix_solver()


def walk(
    layout: Layout,
    steps: Sequence[Sequence[int]],
    config: SolverConfig | None,
    on_verdict: Callable[[int, Verdict], None] | None = None,
) -> list[Verdict | None]:
    """Check every state bottom-up in this process (no deadline)."""
    walker = WarmWalker.create(layout, config)
    verdicts: list[Verdict | None] = []
    for index, step in enumerate(steps):
        verdict = (
            walker.check(step)
            if isinstance(walker, WarmWalker)
            else check_state(layout, steps, index, config)
        )
        verdicts.append(verdict)
        if on_verdict is not None:
            on_verdict(index, verdict)
    return verdicts


def check_states(
    layout: Layout,
    steps: Sequence[Sequence[int]],
    config: SolverConfig | None,
    *,
    deadline: float | None = None,
    workers: int | None = None,
    on_verdict: Callable[[int, Verdict], None] | None = None,
) -> list[Verdict | None]:
    """The verdict after every step; ``None`` where the time ran out first.

    ``deadline`` is a :func:`time.monotonic` timestamp (``None``: no limit).
    With one worker and no deadline the walk runs in this process.
    """
    count = len(steps)
    workers = default_workers() if workers is None else max(1, workers)
    if not count:
        return []
    if workers == 1 and deadline is None:
        return walk(layout, steps, config, on_verdict)
    plan = tuple(tuple(step) for step in steps)
    context = multiprocessing.get_context("spawn")
    claimed = context.Array("b", count)
    results = context.Queue()
    processes = [
        context.Process(
            target=_walker_main if number == 0 else _cold_main,
            args=(layout, plan, config, claimed, results),
            daemon=True,
        )
        for number in range(min(workers, count))
    ]
    verdicts: list[Verdict | None] = [None] * count
    try:
        for process in processes:
            process.start()
        _collect(processes, results, verdicts, deadline, on_verdict)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(timeout=10)
        results.close()
    return verdicts


def _collect(
    processes: Sequence[multiprocessing.process.BaseProcess],
    results: Any,
    verdicts: list[Verdict | None],
    deadline: float | None,
    on_verdict: Callable[[int, Verdict], None] | None,
) -> None:
    """Fill ``verdicts`` from the workers until done, the deadline or no worker."""
    missing = sum(verdict is None for verdict in verdicts)
    while missing:
        left = math.inf if deadline is None else deadline - time.monotonic()
        if left <= 0:
            return
        try:
            index, verdict = results.get(timeout=min(left, POLL_S))
        except queue.Empty:
            if not any(process.is_alive() for process in processes):
                return  # every worker ended (or failed) without the rest
            continue
        if verdict is None:  # a worker failed; its state stays unchecked
            continue
        if verdicts[index] is None:
            missing -= 1
        verdicts[index] = verdict
        if on_verdict is not None:
            on_verdict(index, verdict)


def _claim(claimed: SynchronizedArray[Any], index: int) -> bool:
    with claimed.get_lock():
        if claimed[index]:
            return False
        claimed[index] = 1
        return True


def _claim_highest(claimed: SynchronizedArray[Any]) -> int | None:
    with claimed.get_lock():
        for index in range(len(claimed) - 1, -1, -1):
            if not claimed[index]:
                claimed[index] = 1
                return index
    return None


def _walker_main(
    layout: Layout,
    steps: tuple[tuple[int, ...], ...],
    config: SolverConfig | None,
    claimed: SynchronizedArray[Any],
    results: Any,
) -> None:
    """Bottom-up warm walk until it meets a state a cold worker took."""
    import mesh2brick.backends.legolization  # noqa: F401, PLC0415 - LP attempt order

    walker = WarmWalker.create(layout, config)
    for index, step in enumerate(steps):
        if not _claim(claimed, index):
            return
        try:
            verdict = (
                walker.check(step)
                if isinstance(walker, WarmWalker)
                else check_state(layout, steps, index, config)
            )
        except Exception:  # reported as unchecked, never fatal
            results.put((index, None))
            return
        results.put((index, verdict))


def _cold_main(
    layout: Layout,
    steps: tuple[tuple[int, ...], ...],
    config: SolverConfig | None,
    claimed: SynchronizedArray[Any],
    results: Any,
) -> None:
    """Top-down cold checks until every state is taken."""
    from mesh2brick.backends import legolization  # noqa: PLC0415 - LP attempt order

    legolization.skip_simplex_for_large_lps()

    while (index := _claim_highest(claimed)) is not None:
        try:
            verdict: Verdict | None = check_state(layout, steps, index, config)
        except Exception:  # reported as unchecked, never fatal
            verdict = None
        results.put((index, verdict))
