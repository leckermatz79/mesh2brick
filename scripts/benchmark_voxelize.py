# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Compare mesh2brick's voxelizer with legolization's on the fixtures.

    uv run python scripts/benchmark_voxelize.py [--studs 32] [extra.stl ...]

Prints a Markdown table (paste into docs/benchmarks.md). Both voxelizers get
the same pitch and plate-height cells; volume error is measured against the
mesh volume (for overlapping parts the mesh volume double-counts overlaps).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from mesh2brick.backends.legolization import reference_voxelize
from mesh2brick.config import load_settings
from mesh2brick.ingest import load_model
from mesh2brick.voxel.voxelize import voxelize

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
NAMES = ("cube_10mm", "sphere_r10", "l_bracket", "torus", "bunny_lowpoly")


def main() -> None:
    """Run the comparison and print the table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studs", type=int, default=32)
    parser.add_argument("extra", nargs="*", type=Path)
    args = parser.parse_args()
    settings = load_settings(
        None, [f"input.target_studs={args.studs}", "voxel.height_unit=plate"]
    )
    paths = [FIXTURES / f"{name}.stl" for name in NAMES] + list(args.extra)
    print(
        "| Model | Triangles | Grid (studs x studs x plates) "
        "| mesh2brick cells | Δ volume | time | legolization cells | Δ volume | time |"
    )
    print("|---|---:|---|---:|---:|---:|---:|---:|---:|")
    for path in paths:
        model = load_model(path, settings.input)
        ours = voxelize(model, settings)
        started = time.perf_counter()
        theirs = reference_voxelize(model.mesh, pitch_mm=ours.report.pitch_mm)
        their_seconds = time.perf_counter() - started
        cell_volume = ours.report.pitch_mm**2 * ours.report.cell_height_mm
        mesh_volume = float(model.mesh.volume)
        their_error = (theirs.filled_count * cell_volume - mesh_volume) / mesh_volume
        our_error = ours.report.volume_error or 0.0
        nx, ny, nz = ours.grid.shape
        print(
            f"| {path.stem} | {len(model.mesh.faces):,} | {nx} x {ny} x {nz} "
            f"| {ours.grid.filled_count:,} | {our_error:+.1%} "
            f"| {ours.report.seconds:.2f} s "
            f"| {theirs.filled_count:,} | {their_error:+.1%} | {their_seconds:.2f} s |"
        )


if __name__ == "__main__":
    main()
