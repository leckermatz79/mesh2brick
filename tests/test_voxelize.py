# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Voxelization: lattice/rounding rule, fill fractions, acceptance criteria."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest
import trimesh

from mesh2brick.config import InputConfig, Settings, load_settings, size_overrides
from mesh2brick.ingest import load_model
from mesh2brick.ingest.base import RawModel
from mesh2brick.ingest.normalize import normalize
from mesh2brick.voxel import rays as rays_module
from mesh2brick.voxel.grid import VoxelGrid, lego_cell_height_mm
from mesh2brick.voxel.voxelize import (
    Lattice,
    VoxelizeResult,
    fill_fractions,
    hollow,
    model_pitch,
    plan_lattice,
    round_half_up,
    scale_note,
    target_layers,
    voxelize,
)

if TYPE_CHECKING:
    from mesh2brick.voxel.grid import HeightUnit


def run(mesh: trimesh.Trimesh, *overrides: str) -> VoxelizeResult:
    settings = load_settings(None, list(overrides))
    model = normalize(
        RawModel(parts=(mesh,), names=("m",)), settings.input, source=Path("m.stl")
    )
    return voxelize(model, settings)


def unit_box(
    lo: tuple[float, float, float], hi: tuple[float, float, float]
) -> trimesh.Trimesh:
    lo_a, hi_a = np.asarray(lo), np.asarray(hi)
    box = trimesh.creation.box(extents=hi_a - lo_a)
    box.apply_translation((lo_a + hi_a) / 2)
    return box


# ------------------------------------------------------------------ acceptance
def test_acceptance_cube_is_one_stud_one_brick(fixtures_dir: Path) -> None:
    """SPEC Phase 1: 10 mm cube at mm_per_stud 8 -> 1 x 1 stud, 1 brick high."""
    settings = load_settings(None, ["input.scale_mode=mm", "input.mm_per_stud=8"])
    model = load_model(fixtures_dir / "cube_10mm.stl", settings.input)
    grid = voxelize(model, settings).grid
    assert grid.shape == (1, 1, 1)
    assert grid.filled_count == 1
    assert grid.height_unit == "brick"


@pytest.mark.parametrize("unit", ["brick", "plate"])
def test_acceptance_sphere_volume_within_15_percent(
    fixtures_dir: Path, unit: str
) -> None:
    """SPEC Phase 1: sphere volume deviation < 15 % at target_studs 32."""
    settings = load_settings(
        None, ["input.target_studs=32", f"voxel.height_unit={unit}"]
    )
    model = load_model(fixtures_dir / "sphere_r10.stl", settings.input)
    report = voxelize(model, settings).report
    assert report.method == "volume"
    assert report.volume_error is not None
    assert abs(report.volume_error) < 0.15
    assert abs(report.volume_error) < 0.02  # what we actually achieve


# ------------------------------------------------------------------ rounding rule
@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.4, 0), (0.5, 1), (1.25, 1), (1.5, 2), (2.5, 3), (3.49, 3)],
)
def test_round_half_up(value: float, expected: int) -> None:
    assert round_half_up(value) == expected


def test_lattice_centres_xy_and_starts_at_the_bottom() -> None:
    bounds = np.array([[0.0, 0.0, 2.0], [10.0, 20.0, 12.0]])
    lattice = plan_lattice(bounds, pitch=8.0, height_unit="brick")
    # x: 10/8 = 1.25 -> 1 cell (+2 padding), centred on x = 5
    assert lattice.shape[0] == 3
    assert lattice.origin[0] == pytest.approx(5 - 1.5 * 8)
    # y: 20/8 = 2.5 -> 3 cells (+2), centred on y = 10
    assert lattice.shape[1] == 5
    assert lattice.origin[1] == pytest.approx(10 - 2.5 * 8)
    # z: starts at the lowest point, 10 / 9.6 -> 2 cells
    assert lattice.origin[2] == 2.0
    assert lattice.shape[2] == 2
    assert lattice.cell_height == pytest.approx(9.6)


def test_plate_cells_are_a_third_of_a_brick() -> None:
    bounds = np.array([[0.0, 0.0, 0.0], [8.0, 8.0, 9.6]])
    lattice = plan_lattice(bounds, pitch=8.0, height_unit="plate")
    assert lattice.cell_height == pytest.approx(3.2)
    assert lattice.shape[2] == 3


def test_model_pitch_modes() -> None:
    extents = np.array([30.0, 10.0, 60.0])
    assert model_pitch(extents, Settings()) == pytest.approx(60 / 32)
    mm = load_settings(None, ["input.scale_mode=mm", "input.mm_per_stud=5"])
    assert model_pitch(extents, mm) == 5.0
    with pytest.raises(ValueError, match="no extent"):
        model_pitch(np.zeros(3), Settings())


# ------------------------------------------------------------------ size in cm
@pytest.mark.parametrize(
    ("size", "unit", "shape", "height_cm"),
    [
        # Roadmap 1 acceptance in CI (Duo stays local): the L-bracket is
        # 30 x 10 x 40 mm with a flat top, so its height fills whole layers.
        ("20cm", "brick", (19, 6, 21), 20.16),
        ("30cm", "brick", (28, 9, 31), 29.76),
        ("40cm", "brick", (38, 13, 42), 40.32),
        ("300mm", "brick", (28, 9, 31), 29.76),
        ("30cm", "plate", (28, 9, 94), 30.08),
        ("40cm", "plate", (38, 13, 125), 40.0),
    ],
)
def test_acceptance_size_in_cm_sets_the_height(
    fixtures_dir: Path,
    size: str,
    unit: str,
    shape: tuple[int, int, int],
    height_cm: float,
) -> None:
    settings = load_settings(None, [*size_overrides(size), f"voxel.height_unit={unit}"])
    model = load_model(fixtures_dir / "l_bracket.stl", settings.input)
    grid = voxelize(model, settings).grid
    assert grid.shape == shape
    lego_height_cm = grid.shape[2] * lego_cell_height_mm(grid.height_unit) / 10
    assert lego_height_cm == pytest.approx(height_cm)
    half_layer_cm = lego_cell_height_mm(grid.height_unit) / 20
    target = settings.input.target_height_cm
    assert target is not None
    assert abs(lego_height_cm - target) <= half_layer_cm + 1e-9


@pytest.mark.parametrize(
    ("height_cm", "unit", "layers"),
    [
        (30, "brick", 31),  # 29.76 cm is nearer than 30.72 cm
        (20, "brick", 21),
        (40, "brick", 42),
        (30, "plate", 94),
        (0.1, "brick", 1),  # never less than one layer
        (400, "brick", 417),  # the upper bound of input.target_height_cm
    ],
)
def test_target_layers_rounds_to_the_nearest_layer(
    height_cm: float, unit: HeightUnit, layers: int
) -> None:
    assert target_layers(height_cm, unit) == layers


def test_model_pitch_from_height_fills_whole_layers() -> None:
    settings = load_settings(None, ["input.target_height_cm=30"])
    extents = np.array([67.6, 43.3, 60.0])  # Duo, wider than tall
    pitch = model_pitch(extents, settings)
    assert pitch == pytest.approx(60.0 / (31 * 1.2))
    bounds = np.array([[0.0, 0.0, 0.0], extents])
    assert plan_lattice(bounds, pitch=pitch, height_unit="brick").shape[2] == 31
    with pytest.raises(ValueError, match="no height"):
        model_pitch(np.array([10.0, 10.0, 0.0]), settings)


def test_scale_note_names_what_sets_the_size() -> None:
    assert scale_note(Settings()) == " (longest axis -> 32 studs)"
    cm = load_settings(None, ["input.target_height_cm=30"])
    assert scale_note(cm) == " (height 30 cm -> 31 bricks)"
    plates = load_settings(
        None, ["input.target_height_cm=29.5", "voxel.height_unit=plate"]
    )
    assert scale_note(plates) == " (height 29.5 cm -> 92 plates)"
    assert scale_note(load_settings(None, ["input.scale_mode=mm"])) == ""


# ------------------------------------------------------------------ fractions
def lattice(shape: tuple[int, int, int], height: float = 1.0) -> Lattice:
    return Lattice(origin=(0.0, 0.0, 0.0), pitch=1.0, cell_height=height, shape=shape)


def test_fractions_of_a_box_half_into_a_cell() -> None:
    box = unit_box((0, 0, 0), (1.5, 1, 1))
    fractions = fill_fractions(np.asarray(box.triangles), lattice((2, 1, 1)))
    np.testing.assert_allclose(fractions[:, 0, 0], [1.0, 0.5], atol=1e-6)


def test_fractions_split_exactly_in_height() -> None:
    box = unit_box((0, 0, 0.25), (1, 1, 1.75))
    fractions = fill_fractions(np.asarray(box.triangles), lattice((1, 1, 2)))
    np.testing.assert_allclose(fractions[0, 0], [0.75, 0.75], atol=1e-6)


def test_overlapping_bodies_are_unioned_not_added() -> None:
    a = unit_box((0, 0, 0), (2, 1, 1))
    b = unit_box((1, 0, 0), (3, 1, 1))
    merged = trimesh.util.concatenate([a, b])
    fractions = fill_fractions(np.asarray(merged.triangles), lattice((3, 1, 1)))
    np.testing.assert_allclose(fractions[:, 0, 0], [1, 1, 1], atol=1e-6)


def test_enclosed_cavity_stays_empty() -> None:
    outer = unit_box((0, 0, 0), (3, 3, 3))
    inner = unit_box((1, 1, 1), (2, 2, 2))
    inner.invert()  # a cavity is a body with inward-facing normals
    shell = trimesh.util.concatenate([outer, inner])
    fractions = fill_fractions(np.asarray(shell.triangles), lattice((3, 3, 3)))
    assert fractions[1, 1, 1] == pytest.approx(0.0, abs=1e-6)
    assert fractions.sum() == pytest.approx(26, abs=1e-5)


def test_chunking_does_not_change_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=4.0)
    sphere.apply_translation((5, 5, 5))
    tris = np.asarray(sphere.triangles)
    reference = fill_fractions(tris, lattice((10, 10, 10)))
    monkeypatch.setattr(rays_module, "PAIR_CHUNK", 37)
    np.testing.assert_allclose(fill_fractions(tris, lattice((10, 10, 10))), reference)


def test_threshold_decides_occupancy() -> None:
    box = unit_box((0, 0, 0), (12, 8, 9.6))  # 1.5 studs wide at 8 mm pitch
    loose = run(box, "input.scale_mode=mm", "voxel.threshold=0.2")
    strict = run(box, "input.scale_mode=mm", "voxel.threshold=0.9")
    assert loose.grid.shape[0] == 2
    assert strict.grid.shape[0] == 1


def test_tiny_model_warns_instead_of_crashing() -> None:
    sliver = unit_box((0, 0, 0), (2, 2, 2))
    result = run(sliver, "input.scale_mode=mm", "input.mm_per_stud=20")
    assert result.grid.filled_count == 0
    assert "no voxel reached the fill threshold" in result.warnings[0]


def test_grid_metadata(fixtures_dir: Path) -> None:
    settings = load_settings(None, ["input.target_studs=20"])
    model = load_model(fixtures_dir / "l_bracket.stl", settings.input)
    result = voxelize(model, settings)
    grid = result.grid
    assert grid.pitch_mm == pytest.approx(2.0)
    assert grid.shape == (15, 5, 17)
    assert result.report.filled_cells == grid.filled_count
    # The overhanging arm exists: top layer is wider than the bottom one.
    assert grid.occupancy[:, :, -1].sum() > grid.occupancy[:, :, 0].sum()
    assert grid.colors_used == (4,)


def test_surface_fallback_for_open_meshes() -> None:
    closed = trimesh.creation.box(extents=(16, 16, 19.2))
    top = closed.face_normals[:, 2] > 0.5
    open_box = trimesh.Trimesh(
        vertices=closed.vertices, faces=closed.faces[~top], process=False
    )
    # Remove a whole side too, so the hole cannot be patched.
    side = open_box.face_normals[:, 0] > 0.5
    open_box.update_faces(~side)
    result = run(open_box, "input.scale_mode=mm")
    assert result.report.method == "surface"
    assert result.report.mesh_volume_mm3 is None
    assert result.report.volume_error is None
    assert result.grid.filled_count > 0


# ------------------------------------------------------------------ hollow
def test_hollow_keeps_a_shell() -> None:
    solid = VoxelGrid.from_codes(np.full((5, 5, 5), 4, dtype=np.int16))
    assert hollow(solid, 1).filled_count == 125 - 27
    assert hollow(solid, 2).filled_count == 125 - 1
    assert hollow(solid, 3).filled_count == 125
    with pytest.raises(ValueError, match="at least 1"):
        hollow(solid, 0)


def test_hollow_preserves_colours_and_metadata() -> None:
    codes = np.full((3, 3, 3), 15, dtype=np.int16)
    grid = VoxelGrid.from_codes(codes, height_unit="plate", pitch_mm=2.0)
    shell = hollow(grid, 1)
    assert not shell.occupancy[1, 1, 1]
    assert shell.color[1, 1, 1] == -1
    assert shell.colors_used == (15,)
    assert (shell.height_unit, shell.pitch_mm) == ("plate", 2.0)


def test_up_axis_changes_the_grid(fixtures_dir: Path) -> None:
    upright = load_model(fixtures_dir / "l_bracket.stl", InputConfig())
    lying = load_model(fixtures_dir / "l_bracket.stl", InputConfig(up_axis="x"))
    assert np.argmax(upright.mesh.extents) == 2
    assert np.argmax(lying.mesh.extents) != 2
