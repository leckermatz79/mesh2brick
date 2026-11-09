# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Benchmark stability-checked step planning on finished layouts (Roadmap 3).

    uv run python scripts/benchmark_sequencing.py \\
        out/release-1.3/bunny_lowpoly/bunny_lowpoly.mpd ... \\
        --timeout 1500 --json out/sequencing/results.json [--set KEY=VALUE]

Every input (an ``.mpd``/``.ldr`` written by ``convert``) is read back
strictly, so placement is not repeated, and only the step planner runs, in
its own process with a hard wall-clock timeout, one input after the other
(timings are only comparable without other load). It records legolization's
telemetry: LPs solved (warm and cold), stability checks answered without an
LP (a part not connected to the ground), candidate states evaluated, and the
steps of the plan with a real verdict ("checked states"). A run that times
out still reports the counts reached so far.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

WARM = ("stability.prefix.probe", "stability.prefix.press")
COLD = ("stability.lp", "stability.rescue.cold_direct")
SHORTCUT = "stability.prefix.floating_shortcut"
STATES = (*WARM, "stability.prefix.remove_probe")
REPORT_EVERY_S = 10.0


def main() -> None:
    """Parse arguments and dispatch to the coordinator or a worker."""
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":  # noqa: PLR2004
        _worker(json.loads(sys.argv[2]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--timeout", type=float, default=1500.0)
    parser.add_argument("--json", type=Path)
    parser.add_argument(
        "--set", action="append", default=[], dest="overrides", help="KEY=VALUE"
    )
    parser.add_argument(
        "--planner",
        default="legolization",
        help="planner to run (see PLANNERS in the worker)",
    )
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    for path in args.inputs:
        job = {
            "input": str(path),
            "overrides": args.overrides,
            "planner": args.planner,
        }
        rows.append(_run(job, args.timeout))
        print(json.dumps(rows[-1]), flush=True)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    _print_table(rows)


def _run(job: dict[str, Any], timeout: float) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False) as log:
        job = {**job, "log": log.name}
    started = time.perf_counter()
    status = "ok"
    try:
        done = subprocess.run(
            [sys.executable, __file__, "--worker", json.dumps(job)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if done.returncode != 0:
            status = f"error: {done.stderr[-400:]}"
    except subprocess.TimeoutExpired:
        status = "timeout"
    wall = time.perf_counter() - started
    lines = Path(job["log"]).read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1]) if lines else {}
    return {
        "input": Path(job["input"]).stem,
        "planner": job["planner"],
        "status": status,
        "wall_s": round(wall, 1),
        **last,
    }


class _Counter:
    """Counts LPs and checked states from legolization's span lifecycle."""

    def __init__(self) -> None:
        self.stack: list[list[Any]] = []
        self.warm = self.cold = self.shortcuts = self.states = 0
        self.lp_s = 0.0

    def __call__(self, event: str, name: str, now: float, _telemetry: Any) -> None:
        if event == "start":
            self.stack.append([name, now, False])
            return
        while self.stack and self.stack[-1][0] != name:
            self.stack.pop()
        if not self.stack:
            return
        _, began, shortcut = self.stack.pop()
        if name == SHORTCUT:
            self.shortcuts += 1
            for frame in self.stack:
                frame[2] = True
        elif name in WARM and not shortcut:
            self.warm += 1
            self.lp_s += now - began
        elif name in COLD:
            self.cold += 1
            if not any(frame[0] in WARM for frame in self.stack):
                self.lp_s += now - began
        if name in STATES or (
            name == "stability.analyze"
            and not any(frame[0] in STATES for frame in self.stack)
        ):
            self.states += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "lps": self.warm + self.cold,
            "warm_lps": self.warm,
            "cold_lps": self.cold,
            "no_lp": self.shortcuts,
            "states_evaluated": self.states,
            "lp_s": round(self.lp_s, 1),
        }


def _worker(job: dict[str, Any]) -> None:
    import threading  # noqa: PLC0415

    from legolization import telemetry  # noqa: PLC0415

    from mesh2brick.backends import legolization as backend  # noqa: PLC0415
    from mesh2brick.config import load_settings  # noqa: PLC0415

    log = Path(job["log"])
    layout = backend.layout_from_ldraw(Path(job["input"]))
    settings = load_settings(None, ["steps.sequencing=thorough", *job["overrides"]])
    config = backend.LegolizationBackend().pipeline_config(settings)
    counter = _Counter()
    started = time.monotonic()
    stop = threading.Event()

    def write(extra: dict[str, Any]) -> None:
        row = {
            "parts": len(layout),
            "seconds": round(time.monotonic() - started, 1),
            **counter.snapshot(),
            **extra,
        }
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def report() -> None:
        while not stop.wait(REPORT_EVERY_S):
            write({"done": False})

    threading.Thread(target=report, daemon=True).start()
    with telemetry.record(span_sink=counter):
        plan, checked = _plan(job["planner"], layout, config)
    stop.set()
    unstable = sum(1 for step in plan.steps if not step.prefix_stable)
    import hashlib  # noqa: PLC0415

    fingerprint = hashlib.sha256(
        repr(
            [(s.brick_ids, s.prefix_stable, s.submodel, s.attaches) for s in plan.steps]
        ).encode()
    ).hexdigest()[:10]
    write(
        {
            "done": True,
            "plan": fingerprint,
            "steps": len(plan.steps),
            "checked_states": checked,
            "unstable_steps": unstable,
            "subassemblies": len(plan.subassemblies),
        }
    )


def _plan(  # noqa: PLR0911, PLR0912, PLR0915 - one branch per measured option
    planner: str, layout: Any, config: Any
) -> tuple[Any, int]:
    """Run ``planner``; returns the plan and its number of checked states."""
    from dataclasses import replace  # noqa: PLC0415

    from mesh2brick.backends import legolization as backend  # noqa: PLC0415

    smart = replace(config.instructions, mode="smart", solver=config.solver)
    if planner == "legolization":
        plan = backend.plan_instructions(layout, config=smart)
        return plan, len(plan.steps)
    if planner in {"supported", "warmsub", "a"}:
        from contextlib import ExitStack  # noqa: PLC0415

        import sequencing_prototypes as sequencing  # noqa: PLC0415

        with ExitStack() as stack:
            if planner in {"supported", "a"}:
                stack.enter_context(sequencing.supported_shortcut())
            if planner in {"warmsub", "a"}:
                stack.enter_context(
                    sequencing.warm_subassemblies(supported=planner == "a")
                )
            plan = backend.plan_instructions(layout, config=smart)
        return plan, len(plan.steps)
    if planner.startswith(("layers", "refined")):
        import sequencing_prototypes as sequencing  # noqa: PLC0415

        from mesh2brick.config import StepsConfig  # noqa: PLC0415

        plan = backend.layer_plan(layout, config.instructions)
        if planner.startswith("refined"):
            plan, _, _ = backend.refine_plan(layout, plan, StepsConfig(), checked=False)
        if planner == "layers":
            return plan, 0
        every = int(planner.partition("every")[2] or 1)
        sequencing.LimitedPrefixSolver.solve_on_commit = "lazy" not in planner
        verdicts = sequencing.verify_walk(
            layout,
            [s.brick_ids for s in plan.steps],
            config.solver,
            supported="supported" in planner,
            every=every,
        )
        steps = tuple(
            replace(s, prefix_stable=v[0], prefix_max_score=v[1]) if v else s
            for s, v in zip(plan.steps, verdicts, strict=True)
        )
        return replace(plan, steps=steps), sum(v is not None for v in verdicts)
    if planner.startswith("hybrid"):
        from dataclasses import replace  # noqa: PLC0415

        from mesh2brick.backends import checks  # noqa: PLC0415
        from mesh2brick.config import StepsConfig  # noqa: PLC0415

        workers = int(planner.partition("-")[2] or checks.default_workers())
        plan = backend.layer_plan(layout, config.instructions)
        plan, _, _ = backend.refine_plan(layout, plan, StepsConfig(), checked=False)
        verdicts = checks.check_states(
            layout,
            [s.brick_ids for s in plan.steps],
            config.solver,
            deadline=time.monotonic() + 3600,
            workers=workers,
        )
        new = tuple(
            replace(s, prefix_stable=v.stable, prefix_max_score=v.score) if v else s
            for s, v in zip(plan.steps, verdicts, strict=True)
        )
        return replace(plan, steps=new), sum(v is not None for v in verdicts)
    if planner.startswith("dcheck"):
        return _plan_every_k(planner, layout, config)
    if planner.startswith("pcold"):
        return _plan_pcold(planner, layout, config)
    if planner.startswith("pwalk"):
        return _plan_pwalk(planner, layout, config)
    if planner.startswith("blocks"):
        return _plan_blocks(planner, layout, config, smart)
    if planner.startswith("parallel"):
        return _plan_parallel(planner, layout, smart)
    if planner.startswith("band"):
        from contextlib import ExitStack  # noqa: PLC0415

        import sequencing_prototypes as sequencing  # noqa: PLC0415

        band = replace(smart, fallback="band")
        with ExitStack() as stack:
            if "warmsub" in planner:
                stack.enter_context(sequencing.warm_subassemblies(supported=False))
            plan = backend.plan_instructions(layout, config=band)
        return plan, len(plan.steps)
    if planner.startswith("window"):
        from contextlib import ExitStack  # noqa: PLC0415

        import sequencing_prototypes as sequencing  # noqa: PLC0415

        # window[-W][+warmsub][+supported]
        head, *flags = planner.split("+")
        width = int(head.partition("-")[2] or sequencing.RESCUE_WINDOW_BANDS)
        with ExitStack() as stack:
            if "warmsub" in flags:
                stack.enter_context(
                    sequencing.warm_subassemblies(supported="supported" in flags)
                )
            plan = sequencing.plan_windowed(
                layout, smart, window=width, supported="supported" in flags
            )
        return plan, len(plan.steps)
    msg = f"unknown planner {planner!r}"
    raise SystemExit(msg)


def _plan_blocks(planner: str, layout: Any, config: Any, smart: Any) -> tuple[Any, int]:
    """Option b: plan blocks of bands separately, then check the real states.

    Each block of about ``blocks-N`` parts is planned by legolization alone
    (standing on the table, small LPs); the joined plan's states are then
    checked warm in build order, and sub-assemblies are formed on the result.
    """
    from dataclasses import replace  # noqa: PLC0415

    import sequencing_prototypes as sequencing  # noqa: PLC0415
    from legolization.instructions import subassembly  # noqa: PLC0415

    from mesh2brick.backends import legolization as backend  # noqa: PLC0415

    size = int(planner.partition("-")[2] or 200)
    by_band: dict[int, list[int]] = {}
    for brick in layout:
        by_band.setdefault(brick.layer, []).append(brick.brick_id)
    blocks: list[list[int]] = [[]]
    for band in sorted(by_band):
        if len(blocks[-1]) >= size:
            blocks.append([])
        blocks[-1].extend(by_band[band])
    block_config = replace(smart, subassemblies=False, rotstep=False)
    steps: list[Any] = []
    for block in blocks:
        anchor = min(layout.bricks[b].layer for b in block)
        sub = layout.subset(block).translated(dz=anchor)
        plan = backend.plan_instructions(sub, config=block_config)
        steps.extend(plan.steps)
    from mesh2brick.backends import checks  # noqa: PLC0415

    verdicts = checks.check_states(
        layout,
        [s.brick_ids for s in steps],
        config.solver,
        deadline=time.monotonic() + 3600,
    )
    steps = [
        replace(s, index=i, prefix_stable=v.stable, prefix_max_score=v.score)
        for i, (s, v) in enumerate(zip(steps, verdicts, strict=True), start=1)
        if v is not None
    ]
    warnings = tuple(
        f"step {s.index}: prefix unstable (score {s.prefix_max_score:.2f}); "
        "support the overhang by hand while building"
        for s in steps
        if not s.prefix_stable
    )
    joined = backend.InstructionPlan(
        steps=tuple(steps), warnings=warnings, bom=backend.bill_of_materials(layout)
    )
    with sequencing.warm_subassemblies(supported=False):
        final = subassembly.extract_subassemblies(layout, joined, config=smart)
    return final, len(final.steps)


def _plan_parallel(planner: str, layout: Any, smart: Any) -> tuple[Any, int]:
    """Option c: legolization's planner, rescue candidates solved in parallel.

    In each removal of the rescue, every candidate that needs an LP is
    solved at the same time in a process pool (``parallel-N`` workers); the
    first stable one in legolization's order wins, as before.
    """
    from concurrent.futures import ProcessPoolExecutor  # noqa: PLC0415
    from multiprocessing import get_context  # noqa: PLC0415

    from legolization.instructions import search  # noqa: PLC0415
    from legolization.stability.prefix import (  # noqa: PLC0415
        _floating_shortcut,
        _stud_reach_floating,
    )

    from mesh2brick.backends import legolization as backend  # noqa: PLC0415

    workers = int(planner.partition("-")[2] or 4)
    pool = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=get_context("spawn"),
        initializer=_pool_init,
    )

    def choose(
        layout: Any,
        *,
        candidates: list[int],
        chunks: Any,
        present: set[int],
        config: Any,
        cache: dict[Any, Any],
        remover: Any = None,
    ) -> tuple[int, Any]:
        results: dict[int, Any] = {}
        futures = {}
        for position in candidates:
            rest = frozenset(present - set(chunks[position][1]))
            if not rest:
                return position, None
            if rest in cache:
                results[position] = cache[rest]
                continue
            if remover is not None:
                floating = _stud_reach_floating(
                    rest, remover._grounded, remover._stud_adjacent
                )
                if floating:
                    results[position] = cache[rest] = _floating_shortcut(rest, floating)
                    continue
            futures[position] = pool.submit(
                _pool_analyze, layout.subset(rest), config.solver
            )
        for position, future in futures.items():
            rest = frozenset(present - set(chunks[position][1]))
            results[position] = cache[rest] = future.result()
        best = None
        for position in candidates:
            result = results[position]
            if result.stable:
                return position, result
            if best is None or result.max_score < best[1].max_score:
                best = (position, result)
        assert best is not None
        return best

    original = search._choose_removal
    search._choose_removal = choose
    try:
        plan = backend.plan_instructions(layout, config=smart)
    finally:
        search._choose_removal = original
        pool.shutdown()
    return plan, len(plan.steps)


def _plan_every_k(planner: str, layout: Any, config: Any) -> tuple[Any, int]:
    """Option d on the refined layer plan: every k-th state, bisect on failure.

    ``dcheck-K``: the states after steps K, 2K, ... (and the last) are checked
    with the parallel checker; where one is unstable, the states since the
    last checked one are bisected for the first unstable state. The other
    states stay unchecked.
    """
    from dataclasses import replace  # noqa: PLC0415

    from mesh2brick.backends import checks  # noqa: PLC0415
    from mesh2brick.config import StepsConfig  # noqa: PLC0415

    k = int(planner.partition("-")[2] or 4)
    plan = backend_layer_refined(layout, config, StepsConfig)
    steps = [s.brick_ids for s in plan.steps]
    marks = [*range(k - 1, len(steps), k)]
    if not marks or marks[-1] != len(steps) - 1:
        marks.append(len(steps) - 1)
    merged = [
        tuple(b for s in steps[a + 1 : m + 1] for b in s)
        for a, m in zip([-1, *marks[:-1]], marks, strict=True)
    ]
    found = checks.check_states(
        layout, merged, config.solver, deadline=time.monotonic() + 3600
    )
    verdicts: list[Any] = [None] * len(steps)
    last = -1
    for mark, verdict in zip(marks, found, strict=True):
        verdicts[mark] = verdict
        if verdict is not None and not verdict.stable and mark - last > 1:
            low, high = last + 1, mark
            while low < high:
                middle = (low + high) // 2
                result = checks.check_state(layout, steps, middle, config.solver)
                verdicts[middle] = result
                low, high = (middle + 1, high) if result.stable else (low, middle)
        last = mark
    new = tuple(
        replace(s, prefix_stable=v.stable, prefix_max_score=v.score) if v else s
        for s, v in zip(plan.steps, verdicts, strict=True)
    )
    return replace(plan, steps=new), sum(v is not None for v in verdicts)


def backend_layer_refined(layout: Any, config: Any, steps_config: Any) -> Any:
    """mesh2brick's refined layer plan (layer order + pre-assemblies)."""
    from mesh2brick.backends import legolization as backend  # noqa: PLC0415

    plan = backend.layer_plan(layout, config.instructions)
    plan, _, _ = backend.refine_plan(layout, plan, steps_config(), checked=False)
    return plan


def _plan_pwalk(planner: str, layout: Any, config: Any) -> tuple[Any, int]:
    """Option c on the refined layer plan: states checked by parallel walks.

    ``pwalk-N[+dual][+noipm]``: N processes, each walks a contiguous segment
    of the states warm (its first state solved with the interior-point
    method and crossover).
    """
    import multiprocessing  # noqa: PLC0415
    from dataclasses import replace  # noqa: PLC0415

    import sequencing_prototypes as sequencing  # noqa: PLC0415

    from mesh2brick.backends import legolization as backend  # noqa: PLC0415
    from mesh2brick.config import StepsConfig  # noqa: PLC0415

    head, *flags = planner.split("+")
    workers = int(head.partition("-")[2] or 4)
    options = sequencing.WalkOptions(
        primal="dual" not in flags, start_ipm="noipm" not in flags
    )
    plan = backend.layer_plan(layout, config.instructions)
    plan, _, _ = backend.refine_plan(layout, plan, StepsConfig(), checked=False)
    steps = [s.brick_ids for s in plan.steps]
    sizes = []
    total = 0
    for step in steps:
        total += len(step)
        sizes.append(total)
    starts = sequencing.segment_starts(sizes, workers)
    bounds = list(zip(starts, [*starts[1:], len(steps)], strict=True))
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    procs = [
        context.Process(
            target=_pwalk_worker,
            args=(layout, steps, a, b, config.solver, options, queue),
            daemon=True,
        )
        for a, b in bounds
    ]
    for proc in procs:
        proc.start()
    verdicts: list[Any] = [None] * len(steps)
    while sum(v is not None for v in verdicts) < len(steps):
        index, stable, score = queue.get()
        verdicts[index] = (stable, score)
    for proc in procs:
        proc.join()
    new = tuple(
        replace(s, prefix_stable=v[0], prefix_max_score=v[1])
        for s, v in zip(plan.steps, verdicts, strict=True)
    )
    print(json.dumps({"segments": bounds}), file=sys.stderr)
    return replace(plan, steps=new), len(steps)


def _pwalk_worker(  # noqa: PLR0917 - process target
    layout: Any,
    steps: Any,
    start: int,
    stop: int,
    solver: Any,
    options: Any,
    queue: Any,
) -> None:
    import sequencing_prototypes as sequencing  # noqa: PLC0415

    sequencing.walk_segment(
        layout,
        steps,
        start,
        stop,
        solver,
        options,
        lambda i, stable, score: queue.put((i, stable, score)),
    )


_POOL: dict[str, Any] = {}


def _pcold_init(layout: Any, steps: Any, solver: Any) -> None:
    import mesh2brick.backends.legolization  # noqa: F401, PLC0415 - LP patches

    _POOL.update(layout=layout, steps=steps, solver=solver)


def _pcold_check(index: int) -> tuple[int, bool, float, float]:
    from mesh2brick.backends import legolization as backend  # noqa: PLC0415

    started = time.monotonic()
    ids = {b for step in _POOL["steps"][: index + 1] for b in step}
    result = backend.analyze(_POOL["layout"].subset(ids), _POOL["solver"])
    return index, result.stable, result.max_score, time.monotonic() - started


def _plan_pcold(planner: str, layout: Any, config: Any) -> tuple[Any, int]:
    """Option c, cold: every state of the refined layer plan solved on its own
    in a process pool of ``pcold-N`` workers (biggest states first)."""
    from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: PLC0415
    from dataclasses import replace  # noqa: PLC0415
    from multiprocessing import get_context  # noqa: PLC0415

    from mesh2brick.backends import legolization as backend  # noqa: PLC0415
    from mesh2brick.config import StepsConfig  # noqa: PLC0415

    workers = int(planner.partition("-")[2] or 8)
    plan = backend.layer_plan(layout, config.instructions)
    plan, _, _ = backend.refine_plan(layout, plan, StepsConfig(), checked=False)
    steps = [s.brick_ids for s in plan.steps]
    verdicts: list[Any] = [None] * len(steps)
    seconds = []
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=get_context("spawn"),
        initializer=_pcold_init,
        initargs=(layout, steps, config.solver),
    ) as pool:
        order = range(len(steps) - 1, -1, -1) if "big" in planner else range(len(steps))
        futures = [pool.submit(_pcold_check, i) for i in order]
        for future in as_completed(futures):
            index, stable, score, took = future.result()
            verdicts[index] = (stable, score)
            seconds.append(took)
    print(
        json.dumps({"cpu_s": round(sum(seconds), 1), "max_s": round(max(seconds), 1)}),
        file=sys.stderr,
    )
    new = tuple(
        replace(s, prefix_stable=v[0], prefix_max_score=v[1])
        for s, v in zip(plan.steps, verdicts, strict=True)
    )
    return replace(plan, steps=new), len(steps)


def _pool_init() -> None:
    import mesh2brick.backends.legolization  # noqa: F401, PLC0415 - LP patches


def _pool_analyze(layout: Any, solver: Any) -> Any:
    from mesh2brick.backends import legolization as backend  # noqa: PLC0415

    return backend.analyze(layout, solver)


def _print_table(rows: list[dict[str, Any]]) -> None:
    print()
    print(
        "| Input | Planner | Parts | Result | Sequencing s | Steps | Checked states "
        "| States evaluated | LPs (warm / cold) | No LP | LP s | Unstable steps |"
    )
    print("|---|---|---:|---|---:|---:|---:|---:|---|---:|---:|---:|")
    for r in rows:
        result = "ok" if r.get("done") else r["status"]
        print(
            f"| {r['input']} | {r['planner']} | {r.get('parts', 0):,} | {result} "
            f"| {r.get('seconds', r['wall_s']):.0f} | {r.get('steps', '-')} "
            f"| {r.get('checked_states', '-')} | {r.get('states_evaluated', 0):,} "
            f"| {r.get('lps', 0):,} "
            f"({r.get('warm_lps', 0):,} / {r.get('cold_lps', 0):,}) "
            f"| {r.get('no_lp', 0):,} | {r.get('lp_s', 0):.0f} "
            f"| {r.get('unstable_steps', '-')} |"
        )


if __name__ == "__main__":
    main()
