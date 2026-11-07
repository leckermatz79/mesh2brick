# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Benchmark instruction quality: step sizes, hanging parts, PDF size and time.

    uv run python scripts/benchmark_instructions.py \\
        tests/fixtures/bunny_lowpoly.stl@16 tests/fixtures/bunny_lowpoly.stl@32 \\
        --jobs 4 --out /tmp/instructions

Each ``MODEL@STUDS`` input is voxelized, placed and written as a PDF in its own
process. The step plan is measured twice: as the backend made it ("before")
and after mesh2brick's own step passes (ADR 0012). Prints a Markdown table.
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="MODEL@STUDS")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("out/benchmark"))
    parser.add_argument("--language", default="de")
    args = parser.parse_args()
    jobs = [(text, args.out, args.language) for text in args.inputs]
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(_run, jobs))
    _print_table(results)


def _run(job: tuple[str, Path, str]) -> dict[str, Any]:
    from mesh2brick.backends import legolization as backend  # noqa: PLC0415
    from mesh2brick.config import load_settings  # noqa: PLC0415
    from mesh2brick.export.bom import build_bom  # noqa: PLC0415
    from mesh2brick.ingest import load_model  # noqa: PLC0415
    from mesh2brick.pipeline import palette_for, pdf_options  # noqa: PLC0415
    from mesh2brick.render.pdf import write_instructions  # noqa: PLC0415
    from mesh2brick.steps.metrics import step_stats  # noqa: PLC0415
    from mesh2brick.voxel.voxelize import voxelize  # noqa: PLC0415

    text, out, language = job
    source, _, studs = text.rpartition("@")
    path = Path(source)
    name = f"{path.stem}-{studs}"
    settings = load_settings(
        None,
        [
            f"input.target_studs={studs}",
            f"output.dir={out}",
            f"output.language={language}",
        ],
    )
    captured: dict[str, Any] = {}
    original = backend.refine_plan

    def recording(layout: Any, plan: Any, steps: Any, *, checked: bool) -> Any:
        captured["before"] = backend.to_brick_model(
            layout, plan, name="before", checked=checked
        )
        return original(layout, plan, steps, checked=checked)

    backend.refine_plan = recording  # type: ignore[assignment]
    started = time.monotonic()
    grid = voxelize(
        load_model(path, settings.input), settings, quantize=palette_for(settings)
    ).grid
    placement = backend.LegolizationBackend().place(
        grid,
        settings,
        name=name,
        deadline=started + settings.placement.time_limit_s,
    )
    placed_s = time.monotonic() - started
    model = placement.model
    report = write_instructions(
        model, build_bom(model), out / f"{name}.pdf", pdf_options(settings, name)
    )
    return {
        "name": f"{path.stem} @ {studs}",
        "parts": model.part_count,
        "checked": all(step.stable is not None for step in model.steps),
        "submodels": len(model.submodels),
        "before": asdict(step_stats(captured["before"])),
        "after": asdict(step_stats(model)),
        "pages": report.pages,
        "pdf_mb": round(report.path.stat().st_size / 1e6, 2),
        "pdf_s": report.seconds,
        "place_s": round(placed_s, 1),
    }


def _print_table(results: list[dict[str, Any]]) -> None:
    print(
        "| Model @ studs | Parts | Steps checked | Sub-assemblies | Steps | "
        "Parts per step (min / median / max) | Steps < 3 parts | Hanging parts | "
        "Pre-assemblies | PDF pages | PDF size | PDF time | Placement |"
    )
    print("|---|---:|---|---:|---|---|---|---|---:|---:|---:|---:|---:|")
    for r in results:
        b, a = r["before"], r["after"]
        print(
            f"| {r['name']} | {r['parts']:,} | {'yes' if r['checked'] else 'no'} | "
            f"{r['submodels']} | {b['steps']} → {a['steps']} | "
            f"{b['smallest']} / {b['median']:g} / {b['largest']} → "
            f"{a['smallest']} / {a['median']:g} / {a['largest']} | "
            f"{b['small_steps']} → {a['small_steps']} | "
            f"{b['hanging']} → {a['hanging']} | {a['units']} | {r['pages']} | "
            f"{r['pdf_mb']:.1f} MB | {r['pdf_s']:.0f} s | {r['place_s']:.0f} s |"
        )


if __name__ == "__main__":
    main()
