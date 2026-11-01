# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Smoke and contract tests for the legolization backend adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from mesh2brick.backends import (
    BackendError,
    Exporter,
    Placement,
    Placer,
    StabilityChecker,
    StepSequencer,
)
from mesh2brick.backends.legolization import (
    LegolizationBackend,
    from_lego_grid,
    load_voxel_file,
    to_lego_grid,
)
from mesh2brick.config import Settings, load_settings
from mesh2brick.model import BrickModel
from mesh2brick.voxel.grid import EMPTY, LDU_PER_PLATE, LDU_PER_STUD, VoxelGrid

pytestmark = pytest.mark.ldraw


@pytest.fixture(scope="module")
def backend() -> LegolizationBackend:
    return LegolizationBackend()


@pytest.fixture(scope="module")
def heart(fixtures_dir: Path) -> VoxelGrid:
    return load_voxel_file(fixtures_dir / "heart.vox")


@pytest.fixture(scope="module")
def heart_placement(backend: LegolizationBackend, heart: VoxelGrid) -> Placement:
    return backend.place(heart, Settings(), name="heart")


def _type1_lines(text: str) -> list[list[str]]:
    return [line.split() for line in text.splitlines() if line.startswith("1 ")]


# ------------------------------------------------------------------ smoke test
def test_smoke_heart_vox_to_ldr(
    backend: LegolizationBackend, heart_placement: Placement, tmp_path: Path
) -> None:
    """Phase 0 acceptance: legolization's heart example -> .ldr via our adapter."""
    path = backend.write_ldraw(heart_placement, tmp_path / "heart.ldr")
    text = path.read_text()
    lines = _type1_lines(text)
    model = heart_placement.model

    assert heart_placement.stability.buildable
    assert len(lines) == model.part_count > 0
    # A flat .ldr shows main-model steps only; subassemblies are flattened.
    assert text.count("0 STEP") == model.main_step_count
    assert Counter(line[-1].removesuffix(".dat") for line in lines) == Counter(
        p.part for p in model.parts
    )
    assert {int(line[1]) for line in lines} == {4}  # heart.vox is all red


def test_every_part_is_in_exactly_one_step(heart_placement: Placement) -> None:
    model = heart_placement.model
    attach_steps = {i for i, s in enumerate(model.steps) if s.attaches is not None}
    assert {p.step for p in model.parts} == set(range(model.step_count)) - attach_steps
    assert sum(len(model.parts_in_step(s)) for s in range(model.step_count)) == (
        model.part_count
    )


def test_parts_cover_exactly_the_voxels(
    heart: VoxelGrid, heart_placement: Placement
) -> None:
    """Nothing lost, nothing added: placed cells == filled plate cells."""
    plate_codes = heart.to_plate_codes()
    filled = {tuple(int(v) for v in idx) for idx in np.argwhere(plate_codes != EMPTY)}
    placed = {c for p in heart_placement.model.parts for c in p.cells}
    assert placed == filled


def test_brick_model_json_round_trip(
    heart_placement: Placement, tmp_path: Path
) -> None:
    path = heart_placement.model.save(tmp_path / "heart.bricks.json")
    assert BrickModel.load(path) == heart_placement.model


# ------------------------------------------------------- coordinate round trip
def test_ldraw_positions_match_grid_cells(
    backend: LegolizationBackend, heart_placement: Placement, tmp_path: Path
) -> None:
    """The one z-up -> LDraw(-Y up) transform, checked part by part.

    For a cuboid part covering columns x0..x1, rows y0..y1 and plate layers
    z0..z1, LDraw places its origin at the centre of the top face:
    X = 20 * (x0 + x1) / 2, Z = 20 * (y0 + y1) / 2, Y = -8 * (z1 + 1).
    """
    path = backend.write_ldraw(heart_placement, tmp_path / "heart.ldr")
    written = Counter(
        (line[-1].removesuffix(".dat"), float(line[2]), float(line[3]), float(line[4]))
        for line in _type1_lines(path.read_text())
    )
    expected: Counter[tuple[str, float, float, float]] = Counter()
    for part in heart_placement.model.parts:
        assert part.category in {"brick", "plate"}, "slopes need their own offsets"
        (x0, y0, _), (x1, y1, z1) = part.bounds
        expected[
            (
                part.part,
                LDU_PER_STUD * (x0 + x1) / 2,
                -LDU_PER_PLATE * (z1 + 1),
                LDU_PER_STUD * (y0 + y1) / 2,
            )
        ] += 1
    assert written == expected


def test_grid_round_trip_through_backend(heart: VoxelGrid) -> None:
    assert from_lego_grid(to_lego_grid(heart), height_unit="brick") == heart
    plate = VoxelGrid.from_codes(heart.to_plate_codes(), height_unit="plate")
    assert from_lego_grid(to_lego_grid(plate), height_unit="plate") == plate


def test_from_lego_grid_rejects_partial_bricks(heart: VoxelGrid) -> None:
    plate = VoxelGrid.from_codes(heart.to_plate_codes()[:, :, :-1], height_unit="plate")
    with pytest.raises(BackendError, match="whole bricks"):
        from_lego_grid(to_lego_grid(plate), height_unit="brick")


# ------------------------------------------------------------ backend contract
def test_backend_satisfies_all_protocols(backend: LegolizationBackend) -> None:
    for protocol in (Placer, StabilityChecker, StepSequencer, Exporter):
        assert isinstance(backend, protocol)


def test_strategies_come_from_backend(backend: LegolizationBackend) -> None:
    assert {"greedy", "luo"} <= set(backend.strategies())


def test_check_and_sequence(
    backend: LegolizationBackend, heart_placement: Placement
) -> None:
    assert backend.check(heart_placement, Settings()) == heart_placement.stability
    resequenced = backend.sequence(
        heart_placement, load_settings(None, ["steps.parts_per_step=2"])
    )
    assert resequenced.model.part_count == heart_placement.model.part_count
    assert resequenced.model.step_count > heart_placement.model.step_count


def test_settings_translation(backend: LegolizationBackend) -> None:
    settings = load_settings(
        None,
        [
            "placement.strategy=greedy",
            "placement.seed=7",
            "voxel.wall_thickness=3",
            "parts.categories=[brick, plate, tile]",
            "steps.parts_per_step=5",
            "steps.submodels=false",
            "stability.max_repair_iterations=4",
            "placement.backend_options={colour_mode: soft}",
        ],
    )
    config = backend.pipeline_config(settings, height_unit="brick")
    assert (config.strategy, config.seed) == ("greedy", 7)
    assert (config.shell_studs, config.shell_plates) == (3, 9)
    assert (config.slopes, config.tiles) == (False, True)
    assert config.instructions.target_step_size == 5
    assert config.instructions.subassemblies is False
    assert config.repair_config.max_rounds == 4
    assert config.colour_mode == "soft"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (["placement.strategy=nope"], "unknown placement strategy"),
        (["placement.backend_options={warp_speed: 9}"], "unknown legolization option"),
        (["placement.backend_options={seed: 1}"], "cannot set seed"),
        (["placement.backend_options={solver: {}}"], "nested backend options"),
        (["parts.categories=[brick, slope]"], "needs bricks and plates"),
    ],
)
def test_invalid_backend_settings(
    backend: LegolizationBackend, overrides: list[str], message: str
) -> None:
    with pytest.raises(BackendError, match=message):
        backend.pipeline_config(load_settings(None, overrides))


def test_empty_grid_is_rejected(backend: LegolizationBackend) -> None:
    empty = VoxelGrid.from_codes(np.full((2, 2, 2), EMPTY, dtype=np.int16))
    with pytest.raises(BackendError, match="empty"):
        backend.place(empty, Settings())


def test_unknown_colour_is_rejected(backend: LegolizationBackend) -> None:
    grid = VoxelGrid.from_codes(np.full((1, 1, 1), 9999, dtype=np.int16))
    with pytest.raises(BackendError, match="unknown LDraw colour"):
        backend.place(grid, Settings())


def test_export_needs_own_placement(
    backend: LegolizationBackend, heart_placement: Placement, tmp_path: Path
) -> None:
    foreign = Placement(
        model=heart_placement.model,
        stability=heart_placement.stability,
        backend="other",
    )
    with pytest.raises(BackendError, match="not produced by the legolization"):
        backend.write_ldraw(foreign, tmp_path / "x.ldr")
    with pytest.raises(BackendError, match=r"\.ldr or \.mpd"):
        backend.write_ldraw(heart_placement, tmp_path / "x.dat")


def test_load_voxel_file_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.vox"
    bad.write_bytes(b"not a vox file")
    with pytest.raises(BackendError, match="cannot read"):
        load_voxel_file(bad)
    with pytest.raises(BackendError, match="unsupported voxel file"):
        load_voxel_file(tmp_path / "model.stl")


def test_mpd_keeps_subassemblies_as_submodels(
    backend: LegolizationBackend, heart_placement: Placement, tmp_path: Path
) -> None:
    model = heart_placement.model
    text = backend.write_ldraw(heart_placement, tmp_path / "heart.mpd").read_text()
    assert model.submodels, "heart is expected to contain a subassembly"
    assert text.count("0 FILE ") == 1 + len(model.submodels)
    assert len(_type1_lines(text)) == model.part_count + len(model.submodels)
