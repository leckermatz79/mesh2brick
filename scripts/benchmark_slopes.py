# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Slopes per input across release runs (ROADMAP 8): how many, how many visible.

    uv run python scripts/benchmark_slopes.py out/release-2.0 out/slopes/smooth \\
        out/slopes/mesh --labels 2.0 smooth mesh [--remeasure] \\
        [--local samples/model.3mf] [--json out/slopes/compare.json]

Reads ``results.json`` and the saved models (``<name>.bricks.json``) of each
``scripts/benchmark_release.py`` run and prints one row per input with, per
run: slopes placed (and of them visible: a cell face towards the air around
the model, not the inside of a hollow wall), parts, surface deviation (mean /
95th percentile, recorded by the run, or with ``--remeasure`` measured again
with the current ``mesh2brick.fidelity``: runs before 2.1 counted the sloped
tops on the inner wall of hollow models), one stable piece and seconds.
Nothing is converted.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from benchmark_estimate import run_dir
from benchmark_fidelity import measure as measure_deviation

from mesh2brick.fidelity import visible_parts
from mesh2brick.model import BrickModel


def slope_counts(model: BrickModel) -> dict[str, Any]:
    """Slopes of ``model``: total, visible, per LDraw part."""
    visible = visible_parts(model)
    slopes = [i for i, p in enumerate(model.parts) if p.category == "slope"]
    return {
        "slopes": len(slopes),
        "visible": sum(1 for i in slopes if i in visible),
        "kinds": dict(sorted(Counter(model.parts[i].part for i in slopes).items())),
    }


def measure(
    results: Path, *, remeasure: bool = False, local: list[Path] | None = None
) -> dict[str, dict[str, Any]]:
    """Per input label: slope counts plus what the run recorded (or measured again)."""
    rows = json.loads((results / "results.json").read_text(encoding="utf-8"))
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["exit"]:
            continue
        folder = run_dir(results, row)
        model = BrickModel.load(next(folder.glob("*.bricks.json")))
        deviation = row.get("deviation")
        if remeasure:
            again = measure_deviation(results, row, local or [])
            deviation = again if again is not None else deviation
        found[row["label"]] = {
            **slope_counts(model),
            "parts": model.part_count,
            "deviation": deviation,
            "buildable": row.get("buildable"),
            "seconds": row.get("seconds"),
            "notes": [n for n in row.get("notes", []) if "slope" in n],
        }
    return found


def _cell(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return "-"
    dev = entry.get("deviation") or {}
    deviation = f"{dev['mean_mm']:.2f} / {dev['p95_mm']:.2f}" if dev else "-"
    stable = "yes" if entry.get("buildable") else "NO"
    return (
        f"{entry['slopes']} ({entry['visible']}) · {entry['parts']:,} · "
        f"{deviation} · {stable} · {entry['seconds']:.0f} s"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--labels", nargs="+")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--remeasure", action="store_true")
    parser.add_argument("--local", type=Path, action="append", default=[])
    args = parser.parse_args()
    labels = args.labels or [run.name for run in args.runs]
    measured = {
        label: measure(run, remeasure=args.remeasure, local=args.local)
        for label, run in zip(labels, args.runs, strict=True)
    }
    inputs = list(dict.fromkeys(name for m in measured.values() for name in m))
    print(
        "Per run: slopes (visible) · parts · deviation mean / p95 mm · "
        "one stable piece · time"
    )
    print()
    print("| Input | " + " | ".join(labels) + " |")
    print("|---|" + "---|" * len(labels))
    for name in inputs:
        cells = [_cell(measured[label].get(name)) for label in labels]
        print(f"| {name} | " + " | ".join(cells) + " |")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(measured, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
