# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Benchmark placement configurations on voxel grids or meshes.

    uv run python scripts/benchmark_placement.py out/duo.grid.npz \\
        --config "luo=placement.strategy=luo" \\
        --config "greedy120=placement.strategy=greedy;placement.backend_options=..." \\
        --timeout 420 --jobs 6 --json results.json

Every (input, config) pair runs in its own process with a hard wall-clock
timeout. Workers log legolization's phase spans as they happen, so a run that
times out still shows which phase it was stuck in. Prints a Markdown table.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

PHASES = ("phase.place", "phase.repair", "phase.remerge", "phase.sequencing")


def main() -> None:
    """Parse arguments and dispatch to the coordinator or a worker."""
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":  # noqa: PLR2004
        _worker(json.loads(sys.argv[2]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument(
        "--config",
        action="append",
        required=True,
        help="NAME=key=value;key=value (mesh2brick --set overrides)",
    )
    parser.add_argument("--timeout", type=float, default=420.0)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    jobs = [
        {"input": str(path), "name": name, "overrides": overrides}
        for path in args.inputs
        for name, overrides in (_parse_config(c) for c in args.config)
    ]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda job: _run(job, args.timeout), jobs))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1))
    _print_table(results)


def _parse_config(text: str) -> tuple[str, list[str]]:
    name, _, rest = text.partition("=")
    return name, [part for part in rest.split(";") if part]


def _run(job: dict[str, Any], timeout: float) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False) as log:
        job = {**job, "log": log.name}
    started = time.perf_counter()
    try:
        done = subprocess.run(
            [sys.executable, __file__, "--worker", json.dumps(job)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        status = "ok" if done.returncode == 0 else f"error: {done.stderr[-300:]}"
    except subprocess.TimeoutExpired:
        status = "timeout"
    wall = time.perf_counter() - started
    events = [json.loads(line) for line in Path(job["log"]).read_text().splitlines()]
    Path(job["log"]).unlink(missing_ok=True)
    result: dict[str, Any] = {
        "input": Path(job["input"]).name,
        "config": job["name"],
        "status": status,
        "wall_s": round(wall, 1),
    }
    open_phases: dict[str, float] = {}
    for event in events:
        if event.get("kind") == "span":
            if event["event"] == "start":
                open_phases[event["name"]] = event["t"]
            elif event["name"] in open_phases:
                start = open_phases.pop(event["name"])
                result[event["name"]] = round(event["t"] - start, 1)
        elif event.get("kind") == "result":
            result.update(event["data"])
    if status == "timeout" and open_phases:
        result["stuck_in"] = max(open_phases, key=lambda name: open_phases[name])
    return result


def _worker(job: dict[str, Any]) -> None:
    from legolization import telemetry  # noqa: PLC0415 - heavy, worker only

    from mesh2brick.backends.legolization import LegolizationBackend  # noqa: PLC0415
    from mesh2brick.config import load_settings  # noqa: PLC0415
    from mesh2brick.ingest import load_model  # noqa: PLC0415
    from mesh2brick.voxel.io import load_npz  # noqa: PLC0415
    from mesh2brick.voxel.voxelize import voxelize  # noqa: PLC0415

    log = Path(job["log"]).open("a", encoding="utf-8")  # noqa: SIM115
    origin = time.perf_counter()

    def emit(kind: str, **data: Any) -> None:
        log.write(json.dumps({"kind": kind, "t": time.perf_counter() - origin, **data}))
        log.write("\n")
        log.flush()

    def sink(event: str, name: str, _ts: float, _tel: object) -> None:
        if name.startswith(("phase.", "finish.")):
            emit("span", event=event, name=name)

    settings = load_settings(None, job["overrides"])
    path = Path(job["input"])
    if path.suffix == ".npz":
        grid = load_npz(path)
    else:
        grid = voxelize(load_model(path, settings.input), settings).grid
    with telemetry.record(span_sink=sink):
        placement = LegolizationBackend().place(grid, settings, name=path.stem)
    model, stability = placement.model, placement.stability
    emit(
        "result",
        data={
            "cells": grid.filled_count,
            "parts": model.part_count,
            "steps": model.main_step_count,
            "stable": stability.stable,
            "buildable": stability.buildable,
            "components": stability.component_count,
        },
    )


def _print_table(results: list[dict[str, Any]]) -> None:
    header = ["input", "config", "status", "wall_s", *PHASES, "parts", "buildable"]
    print("| " + " | ".join(header) + " | stuck in |")
    print("|" + "---|" * (len(header) + 1))
    for row in results:
        cells = [str(row.get(key, "")) for key in header]
        print("| " + " | ".join(cells) + f" | {row.get('stuck_in', '')} |")


if __name__ == "__main__":
    main()
