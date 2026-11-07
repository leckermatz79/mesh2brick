# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Benchmark the LLM layer on real models: what was accepted, tokens, cost.

    uv run python scripts/benchmark_llm.py \\
        tests/fixtures/toadstool.obj@16 tests/fixtures/bunny_lowpoly.stl@32:en \\
        --out /tmp/llm

Each ``MODEL@STUDS[:LANGUAGE]`` input runs the full ``convert`` with
``llm.enabled=true`` against the Anthropic API (this costs money; the run
stops at ``llm.max_cost_usd`` per model). Runs are not recorded in the
feedback store. Prints a Markdown table.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="MODEL@STUDS[:LANGUAGE]")
    parser.add_argument("--out", type=Path, default=Path("out/benchmark-llm"))
    parser.add_argument("--set", action="append", default=[], dest="overrides")
    args = parser.parse_args()
    rows = [_run(text, args.out, args.overrides) for text in args.inputs]
    _print_table(rows)


def _run(text: str, out: Path, overrides: list[str]) -> dict[str, Any]:
    from mesh2brick.config import load_settings  # noqa: PLC0415
    from mesh2brick.pipeline import convert  # noqa: PLC0415

    source, _, rest = text.rpartition("@")
    studs, _, language = rest.partition(":")
    path = Path(source)
    name = f"{path.stem}-{studs}"
    settings = load_settings(
        None,
        [
            f"input.target_studs={studs}",
            f"output.dir={out}",
            f"output.language={language or 'de'}",
            "llm.enabled=true",
            "llm.feedback=false",
            *overrides,
        ],
    )
    result = convert(path, settings, name=name, progress=print)
    report = result.llm
    if report is None:
        msg = f"{name}: the LLM layer did not run ({result.warnings})"
        raise SystemExit(msg)
    tasks = {task.task: task for task in report.tasks}
    group = report.outputs.get("group_steps", {})
    usage = report.usage
    return {
        "name": name,
        "language": settings.output.language,
        "parts": result.model.part_count,
        "steps": result.model.step_count,
        "merges": len(group.get("merges", [])),
        "sections": len(group.get("sections", {})),
        "texts": tasks["write_step_text"].detail if "write_step_text" in tasks else "-",
        "requests": usage.requests,
        "input": usage.input_tokens
        + usage.cache_write_tokens
        + usage.cache_read_tokens,
        "cached": usage.cache_read_tokens,
        "output": usage.output_tokens,
        "cost": report.cost_usd,
        "seconds": report.seconds,
        "statuses": ", ".join(f"{t.task} {t.status}" for t in report.tasks),
    }


def _print_table(rows: list[dict[str, Any]]) -> None:
    print()
    print(
        "| Model | Lang | Parts | Steps | Merges | Sections | Step texts | Requests "
        "| Input tokens (cached) | Output tokens | Cost | Time |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        cost = "?" if r["cost"] is None else f"${r['cost']:.3f}"
        print(
            f"| {r['name']} | {r['language']} | {r['parts']} | {r['steps']} "
            f"| {r['merges']} | {r['sections']} | {r['texts']} | {r['requests']} "
            f"| {r['input']:,} ({r['cached']:,}) | {r['output']:,} | {cost} "
            f"| {r['seconds']:.0f} s |"
        )
    for r in rows:
        print(f"- {r['name']}: {r['statuses']}")


if __name__ == "__main__":
    main()
