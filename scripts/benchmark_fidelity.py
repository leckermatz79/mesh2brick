# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Shape fidelity of finished conversions: surface deviation to the input mesh.

    uv run python scripts/benchmark_fidelity.py --results out/release-1.5 \\
        [--local samples/model.3mf] [--json out/fidelity-1.6.json]

The metric of the 2.0 series (ROADMAP, ``mesh2brick.fidelity``): how far the
outside of the brick model (studs included) lies from the mesh it was made
from, as area-weighted mean and 95th percentile in mm and studs. Reads
``results.json`` of a ``scripts/benchmark_release.py`` run, and per input the
saved model (``<name>.bricks.json``) and voxel grid (``<name>.grid.npz``),
which fixes where the mesh sits. Nothing is converted.

Runs recorded before 2.0 do not store their input path: fixtures are found by
their label, the castle next to the results, and local models through
``--local`` (matched by file stem).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from benchmark_estimate import run_dir
from benchmark_release import CASTLE_CONFIG, FIXTURES

from mesh2brick.config import load_settings
from mesh2brick.model import BrickModel
from mesh2brick.pipeline import shape_deviation
from mesh2brick.voxel.io import load_npz


def source_of(results: Path, row: dict[str, Any], local: list[Path]) -> Path | None:
    """The input file of one release-run row (``None``: not found)."""
    if row.get("source"):
        return Path(row["source"])
    label: str = row["label"]
    first = label.split(" ", maxsplit=1)[0]
    if label.startswith("castle"):
        return results / "castle.step"
    if (FIXTURES / first).is_file():
        return FIXTURES / first
    stem = first.split("@", maxsplit=1)[0]
    return next((path for path in local if path.stem == stem), None)


def measure(
    results: Path, row: dict[str, Any], local: list[Path]
) -> dict[str, Any] | None:
    """Deviation numbers of one row, or ``None`` if its input is missing."""
    source = source_of(results, row, local)
    if source is None or not source.is_file():
        return None
    folder = run_dir(results, row)
    model = BrickModel.load(next(folder.glob("*.bricks.json")))
    grid = load_npz(next(folder.glob("*.grid.npz")))
    config = CASTLE_CONFIG if row["label"].startswith("castle") else row.get("config")
    settings = load_settings(config, row.get("set", []))
    started = time.perf_counter()
    deviation = shape_deviation(source, settings, model, grid)
    return {
        "label": row["label"],
        "parts": model.part_count,
        "tiles": sum(1 for p in model.parts if p.category == "tile"),
        **deviation.as_dict(),
        "seconds": round(time.perf_counter() - started, 2),
    }


def print_table(measured: list[dict[str, Any]]) -> None:
    """Markdown table of :func:`measure` rows."""
    print(
        "| Input | Parts | Tiles | Mean mm | p95 mm | Mean studs | p95 studs "
        "| Samples | s |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in measured:
        print(
            f"| {row['label']} | {row['parts']:,} | {row['tiles']} "
            f"| {row['mean_mm']:.2f} | {row['p95_mm']:.2f} "
            f"| {row['mean_studs']:.3f} | {row['p95_studs']:.3f} "
            f"| {row['samples']:,} | {row['seconds']:.1f} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("out/release"))
    parser.add_argument("--local", type=Path, action="append", default=[])
    parser.add_argument("--json", type=Path, help="also write the numbers here")
    args = parser.parse_args()
    rows = json.loads((args.results / "results.json").read_text(encoding="utf-8"))
    measured: list[dict[str, Any]] = []
    for row in rows:
        if row["exit"]:
            continue
        found = measure(args.results, row, args.local)
        if found is None:
            print(f"skipped {row['label']}: input not found (use --local)")
            continue
        measured.append(found)
    print_table(measured)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(measured, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
