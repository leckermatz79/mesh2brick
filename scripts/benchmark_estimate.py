# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Part estimate of ``inspect`` against finished conversions (Roadmap 5).

    uv run python scripts/benchmark_estimate.py --results out/release-1.5

Reads ``results.json`` of a ``scripts/benchmark_release.py`` run and, for
every converted input, the saved voxel grid (``<name>.grid.npz``) and the
placed part count. Recomputes the estimate with the current code (default
settings: hollow, wall 2, as the release run) and prints estimate, range and
whether the real count lies inside, next to the estimate the run recorded.
Nothing is converted, so this takes seconds.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from mesh2brick.voxel.estimate import parts_estimate
from mesh2brick.voxel.io import load_npz


def run_dir(results: Path, row: dict[str, Any]) -> Path:
    """Directory of one converted input inside a release run."""
    if row.get("dir"):
        return Path(row["dir"])
    label: str = row["label"]
    stem = Path(label.split(" ", maxsplit=1)[0]).stem
    if "@" in label:  # --local MODEL@STUDS[:SECONDS]
        size = label.split("@")[1].split(" ", maxsplit=1)[0]
        stem = f"{stem}-{size.replace(':', '-')}"
    return results / stem


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("out/release"))
    args = parser.parse_args()
    rows = json.loads((args.results / "results.json").read_text(encoding="utf-8"))
    print(
        "| Input | Parts | Recorded estimate | Estimate | In range | Width "
        "| Thin cells | Floor cells | ms |"
    )
    print("|---|---:|---|---|---|---:|---:|---:|---:|")
    inside = 0
    widths: list[float] = []
    done = [row for row in rows if not row["exit"]]
    for row in done:
        grid = load_npz(next(run_dir(args.results, row).glob("*.grid.npz")))
        started = time.perf_counter()
        estimate = parts_estimate(grid)
        ms = (time.perf_counter() - started) * 1000
        parts = row["parts"]
        ok = estimate.low <= parts <= estimate.high
        inside += ok
        widths.append(estimate.high / estimate.low)
        low, expected, high = row["estimate"]
        print(
            f"| {row['label']} | {parts:,} | {expected:,} ({low:,}-{high:,}) "
            f"| {estimate.expected:,} ({estimate.low:,}-{estimate.high:,}) "
            f"| {'yes' if ok else 'NO'} | {estimate.high / estimate.low:.2f} "
            f"| {estimate.thin_cells:,} | {estimate.floor_cells:,} | {ms:.0f} |"
        )
    if done:
        print(
            f"\n{inside} of {len(done)} inside the range; range on average a factor "
            f"{sum(widths) / len(widths):.2f} wide"
        )


if __name__ == "__main__":
    main()
