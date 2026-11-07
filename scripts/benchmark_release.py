# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""v1.0 acceptance (SPEC §9): every fixture end to end, plus a big STEP model.

    uv run python scripts/benchmark_release.py --out out/release \\
        [--local samples/model.3mf@32 ...] [--local samples/model.3mf@48:1200]

Runs the real command line (``mesh2brick convert``) once per input, one after
the other, and measures the wall-clock time of the whole process. Afterwards
it checks every result: all output files written, parts list total = parts,
the LDraw file re-reads strictly (every part known to the library, no
duplicates), the model is one stable piece. It also records the hollow-shell
cell count of ``mesh2brick inspect`` to calibrate its rough part estimate.

The STEP case is built on the fly (a small castle of boxes, see
``castle_step``) and converted with ``--config examples/mesh2brick.yaml``,
the literal SPEC §9 command. ``--local`` adds models that must not be
published (only their numbers are printed); ``@STUDS:SECONDS`` also sets
``placement.time_limit_s``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from make_fixtures import step_boxes

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
MODEL_SUFFIXES = {".stl", ".obj", ".ply", ".3mf", ".glb", ".step", ".blend", ".vox"}


def castle_step() -> str:
    """A castle of boxes (mm): wall ring, four towers, a keep; STEP colours."""
    grey, dark, red = (0.63, 0.65, 0.64), (0.39, 0.37, 0.38), (0.7, 0.1, 0.07)
    boxes = [
        ((0, 0, 0), (100, 10, 28), grey),
        ((0, 90, 0), (100, 100, 28), grey),
        ((0, 10, 0), (10, 90, 28), grey),
        ((90, 10, 0), (100, 90, 28), grey),
        ((-6, -6, 0), (16, 16, 42), dark),
        ((84, -6, 0), (106, 16, 42), dark),
        ((-6, 84, 0), (16, 106, 42), dark),
        ((84, 84, 0), (106, 106, 42), dark),
        ((35, 35, 0), (65, 65, 52), grey),
        ((38, 38, 52), (62, 62, 60), red),
        ((-6, -6, 0), (106, 106, 4), grey),  # courtyard: keep and walls are one piece
    ]
    return step_boxes(boxes, name="castle")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("out/release"))
    parser.add_argument(
        "--local", action="append", default=[], help="MODEL@STUDS[:SECONDS]"
    )
    parser.add_argument("--skip-fixtures", action="store_true")
    parser.add_argument("--results", default="results.json", help="file name in OUT")
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    if not args.skip_fixtures:
        cases += [
            {"label": path.name, "path": path, "public": True}
            for path in sorted(FIXTURES.iterdir())
            if path.suffix.lower() in MODEL_SUFFIXES
        ]
    # The generated STEP castle always runs.
    castle = out / "castle.step"
    castle.write_text(castle_step(), encoding="utf-8")
    cases.append(
        {
            "label": "castle.step (generated), --config",
            "path": castle,
            "public": True,
            "config": ROOT / "examples" / "mesh2brick.yaml",
        }
    )
    for text in args.local:
        source, _, size = text.rpartition("@")
        studs, _, limit = size.partition(":")
        path = Path(source)
        overrides = [f"input.target_studs={studs}"]
        if limit:
            overrides.append(f"placement.time_limit_s={limit}")
        cases.append(
            {
                "label": f"{path.stem} @{size} (local)",
                "path": path,
                "public": False,
                "set": overrides,
                "name": f"{path.stem}-{size.replace(':', '-')}",
            }
        )
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(_run(case, out))
        # Written after every case, so a failure late in a long run loses nothing.
        (out / args.results).write_text(
            json.dumps(rows, indent=1, default=str), encoding="utf-8"
        )
    _print_table(rows)


def _run(case: dict[str, Any], out: Path) -> dict[str, Any]:
    from mesh2brick.backends.legolization import LegolizationBackend  # noqa: PLC0415
    from mesh2brick.config import load_settings  # noqa: PLC0415
    from mesh2brick.inspection import inspect_file  # noqa: PLC0415
    from mesh2brick.model import BrickModel  # noqa: PLC0415

    path: Path = case["path"]
    target = out / (case.get("name") or path.stem)
    name = path.stem  # the command names its files after the input file
    overrides: list[str] = case.get("set", [])
    command = [
        sys.executable,
        "-m",
        "mesh2brick",
        "convert",
        str(path),
        "-o",
        str(target),
    ]
    if case.get("config"):
        command += ["--config", str(case["config"])]
    for item in overrides:
        command += ["--set", item]
    print(f"== {case['label']}", flush=True)
    started = time.perf_counter()
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    seconds = time.perf_counter() - started
    row: dict[str, Any] = {
        "label": case["label"],
        "public": case["public"],
        "seconds": round(seconds, 1),
        "exit": done.returncode,
    }
    if done.returncode != 0:
        row["error"] = done.stderr.strip().splitlines()[-1:]
        print(done.stderr, flush=True)
        return row
    model = BrickModel.load(target / f"{name}.bricks.json")
    ldraw = target / f"{name}.mpd"
    files = [
        ldraw,
        target / f"{name}.bom.csv",
        target / f"{name}.bricklink.xml",
        target / f"{name}.rebrickable.csv",
        target / f"{name}.pdf",
    ]
    settings = load_settings(case.get("config"), overrides)
    inspection = inspect_file(path, settings, name=name)
    with (target / f"{name}.bom.csv").open(encoding="utf-8", newline="") as handle:
        bom_total = sum(int(row["quantity"]) for row in csv.DictReader(handle))
    row |= {
        "parts": model.part_count,
        "steps": model.step_count,
        "colours": len(model.colors),
        "buildable": model.buildable,
        "best_so_far": model.best_so_far,
        "stages": _stages(done.stdout),
        "all_files": all(f.is_file() for f in files),
        "bom_total": bom_total,
        "ldraw_parts": LegolizationBackend().verify_ldraw(ldraw),
        "pdf_mb": round((target / f"{name}.pdf").stat().st_size / 1e6, 2),
        "shell_cells": inspection.shell.filled_count,
        "estimate": inspection.parts_estimate,
        "grid": inspection.grid.shape,
    }
    print(json.dumps(row, default=str), flush=True)
    return row


def _stages(stdout: str) -> dict[str, float]:
    """Seconds per stage from the ``time: ... (voxelize 12 s, ...)`` line."""
    line = next((x for x in stdout.splitlines() if x.strip().startswith("time:")), "")
    stages = re.findall(r"(\w+) (\d+) s", line.partition("(")[2])
    return {name: float(seconds) for name, seconds in stages}


def _print_table(rows: list[dict[str, Any]]) -> None:
    print()
    print(
        "| Input | Parts | Steps | Colours | One stable piece | Files + BOM + LDraw ok "
        "| PDF MB | Time s | Shell cells | Parts/cell |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        if row["exit"]:
            print(f"| {row['label']} | failed: {row.get('error')} |")
            continue
        checks = (
            row["all_files"]
            and row["bom_total"] == row["parts"]
            and row["ldraw_parts"] == row["parts"]
        )
        ratio = row["parts"] / row["shell_cells"] if row["shell_cells"] else 0
        print(
            f"| {row['label']} | {row['parts']:,} | {row['steps']} | {row['colours']} "
            f"| {'yes' if row['buildable'] else 'NO'}"
            f"{' (best so far)' if row.get('best_so_far') else ''} "
            f"| {'yes' if checks else 'NO'} "
            f"| {row['pdf_mb']} | {row['seconds']:.0f} | {row['shell_cells']:,} "
            f"| {ratio:.2f} |"
        )


if __name__ == "__main__":
    main()
