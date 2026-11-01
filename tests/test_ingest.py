# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Loader registry, mesh formats and normalisation (orientation, repair)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from mesh2brick.config import InputConfig
from mesh2brick.ingest import IngestError, load_model, loader_for, supported_suffixes
from mesh2brick.ingest.base import RawModel
from mesh2brick.ingest.normalize import (
    UP_ROTATIONS,
    normalize,
    stable_rest_rotation,
    up_rotation,
)

FIXTURE_NAMES = ("cube_10mm", "sphere_r10", "l_bracket", "torus", "bunny_lowpoly")


def raw(*meshes: trimesh.Trimesh) -> RawModel:
    return RawModel(parts=meshes, names=tuple(f"p{i}" for i in range(len(meshes))))


def test_supported_suffixes() -> None:
    assert {".stl", ".obj", ".ply", ".3mf"} <= set(supported_suffixes())


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixtures_load_watertight(fixtures_dir: Path, name: str) -> None:
    model = load_model(fixtures_dir / f"{name}.stl", InputConfig())
    assert model.watertight
    assert model.mesh.volume > 0
    assert len(model.face_part) == len(model.mesh.faces)
    assert not model.face_part.flags.writeable


@pytest.mark.parametrize("suffix", [".obj", ".ply"])
def test_other_mesh_formats(tmp_path: Path, fixtures_dir: Path, suffix: str) -> None:
    mesh = trimesh.load(fixtures_dir / "l_bracket.stl")
    path = tmp_path / f"bracket{suffix}"
    mesh.export(path)
    model = load_model(path, InputConfig())
    np.testing.assert_allclose(model.mesh.extents, [30, 10, 40], atol=1e-6)


def test_unsupported_and_missing_files(tmp_path: Path) -> None:
    with pytest.raises(IngestError, match=r"unsupported input format '\.step'"):
        loader_for(Path("model.step"))
    with pytest.raises(IngestError, match="not found"):
        load_model(tmp_path / "nothing.stl", InputConfig())


def test_unreadable_and_empty_files(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.ply"
    garbage.write_bytes(b"\x00\x01 definitely not a ply")
    with pytest.raises(IngestError):
        load_model(garbage, InputConfig())
    points = tmp_path / "points.ply"
    trimesh.PointCloud(np.random.default_rng(0).random((10, 3))).export(points)
    with pytest.raises(IngestError, match="no triangle faces"):
        load_model(points, InputConfig())


def test_raw_model_validation() -> None:
    with pytest.raises(IngestError, match="no mesh geometry"):
        RawModel(parts=(), names=())
    with pytest.raises(ValueError, match="one name per part"):
        RawModel(parts=(trimesh.creation.box(),), names=())


@pytest.mark.parametrize("axis", list(UP_ROTATIONS))
def test_up_rotations_are_proper_and_map_axis_to_z(axis: str) -> None:
    rotation = up_rotation(axis)  # type: ignore[arg-type]
    assert np.isclose(np.linalg.det(rotation), 1.0)
    np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-12)
    sign = -1.0 if axis.startswith("-") else 1.0
    source = np.zeros(3)
    source["xyz".index(axis[-1])] = sign
    np.testing.assert_allclose(rotation @ source, [0, 0, 1], atol=1e-12)


def test_y_up_model_stands_up() -> None:
    tall_in_y = trimesh.creation.box(extents=(10, 40, 20))
    model = normalize(raw(tall_in_y), InputConfig(up_axis="y"), source=Path("y.obj"))
    np.testing.assert_allclose(model.mesh.extents, [10, 20, 40], atol=1e-9)


def test_auto_orient_rests_on_most_stable_side() -> None:
    tower = trimesh.creation.box(extents=(10, 10, 40))
    model = normalize(raw(tower), InputConfig(auto_orient=True), source=Path("t.stl"))
    assert model.mesh.extents[2] == pytest.approx(10)
    assert any("auto_orient" in w for w in model.warnings)


def test_stable_rest_rotation_keeps_already_resting_model() -> None:
    slab = trimesh.creation.box(extents=(40, 30, 5))
    np.testing.assert_allclose(stable_rest_rotation(slab), np.eye(3), atol=1e-9)


def test_inverted_normals_are_fixed() -> None:
    box = trimesh.creation.box(extents=(10, 10, 10))
    box.invert()
    assert box.volume < 0
    model = normalize(raw(box), InputConfig(), source=Path("inv.stl"))
    assert model.mesh.volume == pytest.approx(1000)


def test_small_hole_is_filled() -> None:
    box = trimesh.creation.box(extents=(10, 10, 10))
    box.update_faces(np.arange(len(box.faces)) != 0)  # drop one triangle
    assert not box.is_watertight
    model = normalize(raw(box), InputConfig(), source=Path("hole.stl"))
    assert model.watertight
    assert any("filled holes" in w for w in model.warnings)
    assert model.face_part[-1] == -1  # the patch belongs to no original part


def test_open_mesh_is_reported() -> None:
    tube = trimesh.creation.cylinder(radius=5, height=20, sections=32)
    caps = np.abs(tube.face_normals[:, 2]) > 0.5
    tube.update_faces(~caps)
    model = normalize(raw(tube), InputConfig(), source=Path("tube.stl"))
    assert not model.watertight
    assert any("not watertight" in w for w in model.warnings)


def test_degenerate_faces_are_dropped() -> None:
    box = trimesh.creation.box(extents=(10, 10, 10))
    faces = np.vstack([box.faces, [[0, 0, 1]]])
    broken = trimesh.Trimesh(vertices=box.vertices, faces=faces, process=False)
    model = normalize(raw(broken), InputConfig(), source=Path("deg.stl"))
    assert len(model.mesh.faces) == 12
    assert len(model.face_part) == 12
    assert any("degenerate" in w for w in model.warnings)


def test_parts_are_merged_with_face_ownership() -> None:
    a = trimesh.creation.box(extents=(1, 1, 1))
    b = trimesh.creation.box(extents=(1, 1, 1))
    b.apply_translation((5, 0, 0))
    model = normalize(raw(a, b), InputConfig(), source=Path("two.3mf"))
    assert model.part_count == 2
    assert sorted(set(model.face_part.tolist())) == [0, 1]
