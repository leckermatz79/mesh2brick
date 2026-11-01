# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""SPEC Phase 1 acceptance: every fixture runs through legolization.

Placed at 12 studs to keep CI fast: legolization's stability LPs grow quickly
with model size (see docs/benchmarks.md). The voxelization itself is checked
at full size in test_voxelize.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mesh2brick.backends.legolization import LegolizationBackend
from mesh2brick.config import load_settings
from mesh2brick.ingest import load_model
from mesh2brick.voxel.voxelize import voxelize

pytestmark = [pytest.mark.ldraw, pytest.mark.slow]

FIXTURES = ("cube_10mm", "sphere_r10", "l_bracket", "torus", "bunny_lowpoly")


@pytest.fixture(scope="module")
def backend() -> LegolizationBackend:
    return LegolizationBackend()


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_runs_through_legolization(
    backend: LegolizationBackend, fixtures_dir: Path, tmp_path: Path, name: str
) -> None:
    settings = load_settings(None, ["input.target_studs=12"])
    model = load_model(fixtures_dir / f"{name}.stl", settings.input)
    grid = voxelize(model, settings).grid
    placement = backend.place(grid, settings, name=name)

    ldr = backend.write_ldraw(placement, tmp_path / f"{name}.ldr")
    part_lines = [
        line for line in ldr.read_text().splitlines() if line.startswith("1 ")
    ]
    assert len(part_lines) == placement.model.part_count > 0
    assert placement.stability.component_count == 1
    assert placement.stability.floating_count == 0
    # Hollowing may remove interior cells, but never adds outside the shape.
    allowed = {
        (int(x), int(y), int(z) * grid.plates_per_cell + k)
        for x, y, z in zip(*grid.occupancy.nonzero(), strict=True)
        for k in range(grid.plates_per_cell)
    }
    slope_free = {
        c for p in placement.model.parts if p.category != "slope" for c in p.cells
    }
    assert slope_free <= allowed
