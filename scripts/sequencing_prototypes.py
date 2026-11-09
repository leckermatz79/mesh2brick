# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Prototypes of Roadmap 3, kept to reproduce docs/benchmarks.md (ADR 0017).

Only ``scripts/benchmark_sequencing.py`` uses this module; what mesh2brick
ships is :mod:`mesh2brick.backends.checks`. The options measured:

* a) incremental: skip the LP for parts that rest with every stud socket on
  fully supported parts (:class:`SupportedPrefixSolver`), re-check steps
  warm after legolization forms sub-assemblies (:func:`warm_subassemblies`),
  re-plan only a window of bands when the greedy pass gets stuck
  (:func:`plan_windowed`);
* d) check only every k-th state, bisect on instability
  (:func:`verify_walk` with ``every=k``);
* warm verification walks, also split into segments for parallel workers
  (:func:`walk_segment`).

Options b) (blocks) and c) (process pools) live in the benchmark script.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, cast

import highspy
from legolization.graph import GROUND_ID, ConnectionGraph
from legolization.instructions import sequencer as _lego_sequencer
from legolization.instructions import subassembly as _lego_subassembly
from legolization.instructions.bom import BillOfMaterials, bill_of_materials
from legolization.instructions.chunking import (
    chunk_bands,
    chunk_centroid,
    mirror_pairs,
)
from legolization.instructions.search import disassembly_order
from legolization.instructions.sequencer import (
    BuildStep,
    InstructionPlan,
    InstructionsConfig,
)
from legolization.stability.prefix import PrefixSolver
from legolization.stability.solver import BrickScore, StabilityResult
from legolization.stability.solver import analyze as _cold_analyze

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from legolization.layout import Layout
    from legolization.stability.solver import SolverConfig

UP: Final = (0, 0, 1)
WARM_LP_TIME_LIMIT_S: Final = 5.0
"""Wall-clock limit per warm solve; a slower one is solved cold instead (the
1.3 attempt order). Without it a warm simplex can stall for minutes."""


class _PerRunLimitHighs(highspy.Highs):
    """``Highs`` whose every ``run()`` gets its own wall-clock limit."""

    limit_s: float = WARM_LP_TIME_LIMIT_S

    def run(self) -> highspy.HighsStatus:
        """Run with ``limit_s`` seconds from now."""
        self.setOptionValue("time_limit", self.getRunTime() + self.limit_s)
        status: highspy.HighsStatus = super().run()
        return status


def _limited_highs(seconds: float) -> highspy.Highs:
    """A fresh warm-solve instance with legolization's prefix-solver options."""
    solver = _PerRunLimitHighs()
    solver.limit_s = seconds
    solver.setOptionValue("output_flag", False)  # noqa: FBT003 - pybind
    solver.setOptionValue("presolve", "off")
    solver.setOptionValue("solver", "simplex")
    solver.setOptionValue("threads", 1)
    return solver


def compression_supported(
    layout: Layout, graph: ConnectionGraph | None = None
) -> frozenset[int]:
    """Parts whose weight goes straight down to the ground in compression.

    A part qualifies if every one of its bottom stud sockets is mated with a
    stud of a qualifying part (or stands on the ground). Such a part never
    needs clutch or friction to stay up, so it cannot make a stable state
    unstable. Parts over a gap, on a tile or half on a cantilever do not
    qualify.
    """
    graph = graph or ConnectionGraph.from_layout(layout)
    mated: dict[int, set[tuple[int, int]]] = {bid: set() for bid in layout.bricks}
    below: dict[int, set[int]] = {bid: set() for bid in layout.bricks}
    for knob in graph.knob_contacts:
        if knob.normal != UP:
            continue
        mated[knob.above_id].add((knob.x, knob.y))
        if knob.below_id != GROUND_ID:
            below[knob.above_id].add(knob.below_id)
    full: set[int] = set()
    for brick in sorted(layout, key=lambda b: (b.layer, b.brick_id)):
        sockets = {
            (c.cell[0], c.cell[1])
            for c in layout.connectors_of(brick, top=False)
            if c.direction[2] != 0
        }
        if (
            sockets
            and sockets <= mated[brick.brick_id]
            and below[brick.brick_id] <= full
        ):
            full.add(brick.brick_id)
    return frozenset(full)


@dataclass(slots=True)
class CheckStats:
    """What :class:`SupportedPrefixSolver` saved."""

    skipped: int = 0
    """Candidate states answered without an LP (fully supported parts)."""
    solved: int = 0
    """Candidate states that needed an LP."""


class LimitedPrefixSolver(PrefixSolver):
    """legolization's warm prefix solver with a time limit per warm solve."""

    solve_on_commit: bool = True

    def __init__(self, layout: Layout, config: SolverConfig) -> None:
        """Build the warm model with a limited HiGHS instance."""
        super().__init__(layout, config)
        self._h = _limited_highs(WARM_LP_TIME_LIMIT_S)

    def commit(self, chunk: tuple[int, ...]) -> None:
        """Advance the base by ``chunk``, solved warm right away.

        legolization appends a chunk it did not just solve (a floating one,
        answered without an LP) unsolved, so the next LP has to solve all of
        them at once; a floating roof or cap then costs one huge LP that runs
        into the time limit and is solved cold (measured: 50 s for the
        cube). Solving each chunk as it comes keeps every warm LP small.
        """
        wanted = frozenset(chunk) - self.present
        pending = self._pending
        if (
            self.solve_on_commit
            and wanted
            and (pending is None or pending.chunk != wanted)
        ):
            try:
                self._rollback()
                self._append(wanted)
                self._h.setBasis(self._extended_basis(self._base_basis))
                self._h.run()
            except Exception:
                self._hard_reset()
            else:
                if self._h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
                    self._rollback()
        super().commit(chunk)


class SupportedPrefixSolver(LimitedPrefixSolver):
    """legolization's warm prefix solver that skips LPs for supported parts.

    The shortcut only answers when the committed base is known to be
    stable; its verdict carries the base's scores (an upper bound: new parts
    in compression need no drag) and score 0 for the new parts.
    """

    supported: frozenset[int]
    stats: CheckStats

    def __init__(self, layout: Layout, config: SolverConfig) -> None:
        """Build the warm model and the fully supported part set."""
        super().__init__(layout, config)
        self.supported = compression_supported(layout, self._graph)
        self.stats = CheckStats()
        self._base: StabilityResult | None = StabilityResult(stable=True)
        self._last: tuple[frozenset[int], StabilityResult] | None = None

    def probe(self, chunk: tuple[int, ...]) -> StabilityResult:
        """Solve base | chunk warm, or answer at once for supported parts."""
        wanted = frozenset(chunk) - self.present
        base = self._base
        if base is not None and base.stable and wanted <= self.supported:
            self._rollback()
            result = _supported_result(base, wanted)
            self.stats.skipped += 1
        else:
            result = super().probe(chunk)
            self.stats.solved += 1
        self._last = (wanted, result)
        return result

    def commit(self, chunk: tuple[int, ...]) -> None:
        """Advance the base by ``chunk`` and remember its verdict if known."""
        wanted = frozenset(chunk) - self.present
        last = self._last
        super().commit(chunk)
        self._base = last[1] if last is not None and last[0] == wanted else None
        self._last = None


def _supported_result(base: StabilityResult, added: frozenset[int]) -> StabilityResult:
    scores = dict(base.scores)
    for bid in added:
        scores[bid] = BrickScore(
            brick_id=bid, score=0.0, drag_max=0.0, in_equilibrium=True
        )
    return StabilityResult(
        stable=True,
        scores=scores,
        weakest_pair=base.weakest_pair,
        min_capacity=base.min_capacity,
        status="supported-shortcut",
        objective=base.objective,
    )


@dataclass(slots=True)
class _WorldWalker:
    """One warm LP model over legolization's rewritten world order."""

    layout: Layout
    solver: PrefixSolver | None
    stats: CheckStats = field(default_factory=CheckStats)

    def analyze(
        self, sub: Layout, config: Any = None, *args: Any, **kwargs: Any
    ) -> StabilityResult:
        ids = frozenset(sub.bricks)
        solver = self.solver
        warm = (
            solver is not None
            and not args
            and not kwargs.get("extra_masses")
            and ids >= solver.present
            and all(sub.bricks[b] is self.layout.bricks.get(b) for b in ids)
        )
        if not warm or solver is None:
            self.stats.skipped += 0
            return _cold_analyze(sub, config, *args, **kwargs)
        added = tuple(sorted(ids - solver.present))
        result = solver.probe(added)
        solver.commit(added)
        self.stats.solved += 1
        return result


@contextmanager
def warm_subassemblies(*, supported: bool = True) -> Iterator[list[CheckStats]]:
    """Let legolization's sub-assembly rewrite re-check steps warm.

    Wraps ``extract_subassemblies``: its re-checks of the main steps and the
    attach steps (``analyze`` in that module) go through one warm prefix
    solver over the growing world. Yields the stats of every rewrite.
    """
    found: list[CheckStats] = []
    namespace = _lego_subassembly.__dict__
    extract = namespace["extract_subassemblies"]

    def wrapped(layout: Layout, plan: Any, *, config: Any) -> Any:
        kind = SupportedPrefixSolver if supported else LimitedPrefixSolver
        walker = _WorldWalker(layout, kind.create(layout, config.solver))
        found.append(walker.stats)
        original = namespace["analyze"]
        namespace["analyze"] = walker.analyze
        try:
            return extract(layout, plan, config=config)
        finally:
            namespace["analyze"] = original

    namespace["extract_subassemblies"] = wrapped
    try:
        yield found
    finally:
        namespace["extract_subassemblies"] = extract


@contextmanager
def supported_shortcut() -> Iterator[None]:
    """Let legolization's greedy pass skip LPs for fully supported parts."""
    namespace = _lego_sequencer.__dict__
    original = namespace["PrefixSolver"]
    namespace["PrefixSolver"] = SupportedPrefixSolver
    try:
        yield
    finally:
        namespace["PrefixSolver"] = original


# ---------------------------------------------------------------- windowed rescue
RESCUE_WINDOW_BANDS: Final = 2
"""Bands a rescue re-plans at first; doubled until their full state stands."""


@dataclass(slots=True)
class _WindowRemover:
    """legolization's ``RemovalSolver`` interface on the warm forward solver.

    ``scope`` is the checked base plus the window's parts still present;
    every removal probe is a warm LP of base plus window minus the chunk.
    """

    solver: PrefixSolver
    scope: set[int]
    base: frozenset[int]

    def probe_without(self, chunk: tuple[int, ...]) -> StabilityResult:
        rest = self.scope - set(chunk) - self.base
        return self.solver.probe(tuple(sorted(rest)))

    def commit_without(self, chunk: tuple[int, ...]) -> None:
        self.scope -= set(chunk)


@dataclass(slots=True)
class WindowStats:
    """How :func:`plan_windowed` spent its stability checks."""

    rescues: int = 0
    window_bands: list[int] = field(default_factory=list)
    """Bands of each rescue window."""


def plan_windowed(
    layout: Layout,
    config: InstructionsConfig,
    *,
    window: int = RESCUE_WINDOW_BANDS,
    supported: bool = False,
    stats: WindowStats | None = None,
) -> InstructionPlan:
    """legolization's step planner with a rescue limited to a few bands.

    Adapted from ``legolization.instructions.sequencer.plan_instructions``
    and ``_sequence`` (legolization 0.5.0, commit
    893414297d4f088106c8416b4110c85a438c8bd8, GPL-3.0-or-later, Copyright
    Harold Martin), greedy path without insertion checks: when no ready chunk
    gives a stable state, legolization re-plans the *whole* rest of the model
    by disassembly, with one cold LP of nearly the whole model per removal.
    Here only the next ``window`` bands are re-planned (doubled until their
    full state is stable), with warm LPs on the checked base, and the greedy
    pass continues above them.
    """
    stats = stats if stats is not None else WindowStats()
    relations = _lego_sequencer._sequencing_relations(layout)
    chunks = chunk_bands(layout, config=config, pairs=mirror_pairs(layout))
    kind = SupportedPrefixSolver if supported else LimitedPrefixSolver
    solver = kind.create(layout, config.solver)
    if solver is None:
        return _lego_sequencer.plan_instructions(layout, config=config)
    steps, warnings = _windowed_sequence(
        layout, config, chunks, relations, solver, window, stats
    )
    plan = InstructionPlan(
        steps=tuple(steps),
        warnings=tuple(warnings),
        bom=BillOfMaterials(total=(), per_step=()),
    )
    if config.subassemblies:
        plan = _lego_subassembly.extract_subassemblies(layout, plan, config=config)
    if config.rotstep:
        rotated = _lego_sequencer._assign_rotsteps_subaware(layout, list(plan.steps))
        plan = replace(plan, steps=tuple(rotated))
    return replace(plan, bom=bill_of_materials(layout, plan=plan))


def _windowed_sequence(  # noqa: PLR0917 - the loop reads all sequencing state
    layout: Layout,
    config: InstructionsConfig,
    chunks: list[tuple[int, tuple[int, ...]]],
    relations: Any,
    solver: PrefixSolver,
    window: int,
    stats: WindowStats,
) -> tuple[list[BuildStep], list[str]]:
    pending = list(range(len(chunks)))
    placed: set[int] = set()
    steps: list[BuildStep] = []
    warnings: list[str] = []
    centroids = [chunk_centroid(layout, chunk) for _, chunk in chunks]
    previous: tuple[float, float] | None = None

    def emit(chunk: tuple[int, ...], *, stable: bool, score: float) -> None:
        steps.append(
            BuildStep(
                index=len(steps) + 1,
                brick_ids=_lego_sequencer._brick_order(layout, chunk),
                prefix_stable=stable,
                prefix_max_score=score,
            )
        )
        placed.update(chunk)
        if not stable:
            warnings.append(
                f"step {len(steps)}: prefix unstable (score {score:.2f}); "
                "support the overhang by hand while building"
            )

    while pending:
        ready = _lego_sequencer._gather_ready(
            pending,
            chunks,
            placed,
            relations.supports,
            relations.blockers,
            relations.blocks,
            limit=config.beam_width,
        )
        if config.spatial_tiebreak and previous is not None:
            ready = _lego_sequencer._spatial_order(ready, chunks, centroids, previous)
        chosen = None
        for position in ready:
            chunk = chunks[position][1]
            result = solver.probe(chunk)
            if result.stable:
                solver.commit(chunk)
                emit(chunk, stable=True, score=result.max_score)
                chosen = position
                break
        if chosen is not None:
            pending.remove(chosen)
        else:
            for position in _rescue_window(
                layout,
                config,
                chunks,
                relations,
                solver,
                pending,
                placed,
                window,
                emit,
                stats,
            ):
                pending.remove(position)
        previous = chunk_centroid(layout, steps[-1].brick_ids)
    return steps, warnings


def _rescue_window(  # noqa: PLR0917 - the rescue reads all sequencing state
    layout: Layout,
    config: InstructionsConfig,
    chunks: list[tuple[int, tuple[int, ...]]],
    relations: Any,
    solver: PrefixSolver,
    pending: list[int],
    placed: set[int],
    window: int,
    emit: Any,
    stats: WindowStats,
) -> list[int]:
    """Re-plan the lowest ``window`` pending bands by disassembly; their positions."""
    bands = sorted({chunks[p][0] for p in pending})
    size = window
    while True:
        top = bands[min(size, len(bands)) - 1]
        members = [p for p in pending if chunks[p][0] <= top]
        ids = tuple(sorted({b for p in members for b in chunks[p][1]}))
        full = solver.probe(ids)
        if full.stable or size >= len(bands):
            break
        size *= 2
    stats.rescues += 1
    stats.window_bands.append(min(size, len(bands)))
    base = frozenset(placed)
    remover = _WindowRemover(solver, set(base) | set(ids), base)
    verdicts = disassembly_order(
        layout,
        placed=base,
        chunks=[chunks[p] for p in members],
        supports=relations.supports,
        blockers=relations.blockers,
        config=config,
        cache={},
        remover=cast("Any", remover),
    )
    for verdict in verdicts:
        emit(verdict.chunk, stable=verdict.stable, score=verdict.max_score)
    solver.probe(ids)  # leaves the solved window as the new warm base
    solver.commit(ids)
    return members


# ---------------------------------------------------------------- verification walk
def verify_walk(
    layout: Layout,
    steps: Sequence[Sequence[int]],
    config: SolverConfig | None,
    *,
    supported: bool = False,
    every: int = 1,
    on_verdict: Callable[[int, bool, float], None] | None = None,
) -> list[tuple[bool, float] | None]:
    """Stability verdict of the state after each of ``steps`` (in order).

    The states only grow, so one warm LP model checks them all (as
    legolization's ``verify_plan`` does). With ``every=k`` only every k-th
    state and the last are checked; where one is unstable, the states since
    the last checked one are bisected for the first unstable state (the
    "every k-th" baseline of Roadmap 3; the states it skips stay ``None``).
    ``on_verdict(index, stable, score)`` sees each verdict as it is found.
    """
    kind = SupportedPrefixSolver if supported else LimitedPrefixSolver
    solver = kind.create(layout, config)
    if solver is None:
        msg = "the warm prefix solver is not available"
        raise RuntimeError(msg)
    verdicts: list[tuple[bool, float] | None] = [None] * len(steps)

    def check(index: int) -> bool:
        wanted = tuple(sorted({b for s in steps[: index + 1] for b in s}))
        result = solver.probe(wanted)
        verdicts[index] = (result.stable, result.max_score)
        if on_verdict is not None:
            on_verdict(index, result.stable, result.max_score)
        return result.stable

    if every <= 1:
        for index, step in enumerate(steps):
            check(index)
            solver.commit(tuple(step))
        return verdicts
    last = -1
    marks = [*range(every - 1, len(steps), every)]
    if not marks or marks[-1] != len(steps) - 1:
        marks.append(len(steps) - 1)
    for mark in marks:
        if not check(mark) and mark - last > 1:
            low, high = last + 1, mark  # first unstable state lies in [low, high]
            while low < high:
                middle = (low + high) // 2
                if check(middle):
                    low = middle + 1
                else:
                    high = middle
        solver.commit(tuple(sorted({b for s in steps[last + 1 : mark + 1] for b in s})))
        last = mark
    return verdicts


# ---------------------------------------------------------------- parallel walk
@dataclass(frozen=True, slots=True)
class WalkOptions:
    """Solver options of one verification walk (benchmarked in Roadmap 3)."""

    primal: bool = True
    """Warm solves with the primal simplex (faster after appending parts)."""
    start_ipm: bool = True
    """Solve a segment's first state from scratch (with presolve) to get a
    basis for the warm solves that follow."""
    start_solver: str = "ipm"
    """HiGHS solver for that first state (``ipm`` with crossover or ``simplex``)."""


def segment_starts(sizes: Sequence[int], workers: int) -> list[int]:
    """Split states of ``sizes`` parts into contiguous segments of equal cost.

    The cost of checking a state grows with its size, so later segments get
    fewer states; returns the first state index of each segment.
    """
    if not sizes:
        return [0]
    costs = [float(size) ** 1.5 for size in sizes]
    total = sum(costs)
    starts = [0]
    running = 0.0
    for index, cost in enumerate(costs):
        if running >= total * len(starts) / workers and index > starts[-1]:
            starts.append(index)
        running += cost
        if len(starts) == workers:
            break
    return starts


def walk_segment(  # noqa: PLR0917 - one worker's share
    layout: Layout,
    steps: Sequence[Sequence[int]],
    start: int,
    stop: int,
    config: SolverConfig | None,
    options: WalkOptions,
    on_verdict: Callable[[int, bool, float], None],
) -> None:
    """Check the states after steps ``start..stop-1`` (one worker's share)."""
    solver = LimitedPrefixSolver.create(layout, config)
    if solver is None:
        msg = "the warm prefix solver is not available"
        raise RuntimeError(msg)
    highs = solver._h
    if options.primal:
        highs.setOptionValue("simplex_strategy", 4)
    before = tuple(sorted({b for step in steps[:start] for b in step}))
    if before:
        solver.solve_on_commit = False
        solver.commit(before)
        solver.solve_on_commit = True
    for index in range(start, stop):
        step = tuple(steps[index])
        first = index == start and before and options.start_ipm
        if first:
            highs.setOptionValue("solver", options.start_solver)
            highs.setOptionValue("presolve", "on")
            highs.setOptionValue("run_crossover", "on")
            limit = highs.limit_s if isinstance(highs, _PerRunLimitHighs) else None
            if isinstance(highs, _PerRunLimitHighs):
                highs.limit_s = START_LP_TIME_LIMIT_S
        try:
            result = solver.probe(step)
        finally:
            if first:
                highs.setOptionValue("solver", "simplex")
                highs.setOptionValue("presolve", "off")
                if isinstance(highs, _PerRunLimitHighs) and limit is not None:
                    highs.limit_s = limit
        on_verdict(index, result.stable, result.max_score)
        solver.commit(step)


START_LP_TIME_LIMIT_S: Final = 300.0
"""Limit for a segment's first solve (interior point with crossover)."""
