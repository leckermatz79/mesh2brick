# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Flat tops: which top cells the input mesh renders flat (ROADMAP 9)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from mesh2brick.config import Settings
from mesh2brick.ingest.base import MeshModel
from mesh2brick.voxel.flat import MIN_FACE_CELLS, flat_tops, top_cells
from mesh2brick.voxel.grid import VoxelGrid
from mesh2brick.voxel.io import load_npz, save_npz
from mesh2brick.voxel.voxelize import (
    fill_fractions,
    hollow,
    plan_lattice,
    voxelize,
)

PITCH = 8.0
"""One stud = 8 model mm, so LEGO mm = model mm."""


def _faces(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """(occupancy, face height over each flat top) at 8 mm per stud, bricks."""
    lattice = plan_lattice(np.asarray(mesh.bounds), pitch=PITCH, height_unit="brick")
    occupancy = fill_fractions(np.asarray(mesh.triangles), lattice) >= 0.5
    faces = flat_tops(
        np.asarray(mesh.triangles), occupancy, lattice, lego_cell_height_mm=9.6
    )
    return occupancy, faces


def _mask(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """(occupancy, flat mask) of ``mesh``."""
    occupancy, faces = _faces(mesh)
    return occupancy, np.isfinite(faces)


def test_the_top_of_a_box_is_flat_everywhere() -> None:
    box = trimesh.creation.box(bounds=[[0, 0, 0], [48, 32, 25]])  # top mid-cell
    occupancy, faces = _faces(box)
    tops = top_cells(occupancy)
    flat = np.isfinite(faces)
    assert flat.sum() == tops.sum() == 6 * 4
    assert np.array_equal(flat, tops)
    # 25 mm = 2.6 bricks: the voxels end at 3 bricks, the face 0.4 bricks lower.
    assert np.allclose(faces[flat], (25 - 3 * 9.6) / 9.6, atol=1e-5)


def _profile(points: list[tuple[float, float]], depth: float) -> trimesh.Trimesh:
    """A prism: ``points`` (x, z, counter-clockwise) extruded ``depth`` along y."""
    profile = np.asarray(points, dtype=float)
    fan = np.array([[0, i, i + 1] for i in range(1, len(points) - 1)])
    prism = trimesh.creation.extrude_triangulation(profile, fan, height=depth)
    prism.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    prism.apply_translation(-prism.bounds[0])
    return prism


def test_stairs_of_a_tilted_plane_are_not_flat() -> None:
    # A wedge: its top rises 20 mm over 64 mm (17°); voxels make stairs of it.
    wedge = _profile([(0, 0), (64, 0), (64, 30), (0, 10)], depth=32)
    occupancy, flat = _mask(wedge)
    assert top_cells(occupancy).sum() > 0
    assert not flat.any()


def test_a_dome_has_no_flat_cells_even_at_its_top() -> None:
    dome = trimesh.creation.icosphere(subdivisions=4, radius=80.0)
    occupancy, flat = _mask(dome)
    assert top_cells(occupancy).sum() > 50
    assert not flat.any()


def test_a_slightly_tilted_top_is_not_flat() -> None:
    box = trimesh.creation.box(bounds=[[0, 0, 0], [64, 64, 20]])
    box.apply_transform(
        trimesh.transformations.rotation_matrix(np.radians(2.0), (0, 1, 0))
    )
    box.apply_translation(-box.bounds[0])
    _occupancy, flat = _mask(box)
    assert not flat.any()


def test_faces_smaller_than_the_minimum_are_dropped() -> None:
    post = trimesh.creation.box(bounds=[[0, 0, 0], [8, 8, 25]])  # one stud wide
    occupancy, flat = _mask(post)
    assert top_cells(occupancy).sum() == 1 < MIN_FACE_CELLS
    assert not flat.any()


def test_border_cells_join_the_face_when_mostly_covered() -> None:
    # 20 mm wide on 8 mm cells, centred: columns 1 and 3 are 75 % covered.
    slab = trimesh.creation.box(bounds=[[0, 0, 0], [20, 32, 19.2]])
    occupancy, flat = _mask(slab)
    assert flat.any(axis=(1, 2)).tolist() == [False, True, True, True, False]
    assert np.array_equal(flat, top_cells(occupancy))


def test_cells_under_a_chamfer_keep_their_studs() -> None:
    # Flat top from x = 0 to 14, then a chamfer down to (20, 12).
    chamfered = _profile([(0, 0), (20, 0), (20, 12), (14, 19.2), (0, 19.2)], 32)
    occupancy, flat = _mask(chamfered)
    columns = flat.any(axis=(1, 2)).tolist()
    assert columns[1:3] == [True, True]
    assert top_cells(occupancy)[3].any()
    assert not columns[3]


def test_voxelize_keeps_the_mask_and_npz_round_trips_it(tmp_path: Path) -> None:
    box = trimesh.creation.box(bounds=[[0, 0, 0], [40, 40, 30]])
    settings = Settings.model_validate(
        {"input": {"scale_mode": "mm", "mm_per_stud": 8.0}}
    )
    model = MeshModel(
        mesh=box, source=Path("box.stl"), part_names=("box",), watertight=True
    )
    grid = voxelize(model, settings).grid
    assert grid.flat is not None
    assert np.array_equal(np.isfinite(grid.flat), top_cells(grid.occupancy))
    loaded = load_npz(save_npz(grid, tmp_path / "g.npz"))
    assert loaded == grid
    assert loaded.flat is not None
    assert np.array_equal(loaded.flat, grid.flat, equal_nan=True)
    shell = hollow(grid, 1).flat
    assert shell is not None
    assert np.isfinite(shell).sum() == np.isfinite(grid.flat).sum()


def test_grids_without_mask_treat_every_top_as_flat() -> None:
    occupancy = np.zeros((2, 2, 2), dtype=bool)
    occupancy[:, :, 0] = True
    occupancy[0, 0, 1] = True
    grid = VoxelGrid(
        occupancy=occupancy, color=np.where(occupancy, 4, -1).astype(np.int32)
    )
    assert grid.flat is None
    faces = grid.flat_tops()
    assert np.isfinite(faces).sum() == 4  # three on the ground layer, one above
    assert np.all(faces[np.isfinite(faces)] == 0)


def test_flat_cells_must_be_occupied() -> None:
    occupancy = np.zeros((1, 1, 2), dtype=bool)
    occupancy[0, 0, 0] = True
    with pytest.raises(ValueError, match="not occupied"):
        VoxelGrid(
            occupancy=occupancy,
            color=np.where(occupancy, 4, -1).astype(np.int32),
            flat=np.where(occupancy, np.nan, 0.0).astype(np.float32),
        )


def test_a_mesh_without_up_facing_faces_has_no_flat_tops() -> None:
    box = trimesh.creation.box(bounds=[[0, 0, 0], [16, 16, 19.2]])
    bottom_only = trimesh.Trimesh(
        vertices=box.vertices,
        faces=box.faces[box.face_normals[:, 2] < -0.5],
        process=False,
    )
    lattice = plan_lattice(np.asarray(box.bounds), pitch=PITCH, height_unit="brick")
    occupancy = np.zeros(lattice.shape, dtype=bool)
    occupancy[1:3, 1:3, :2] = True
    faces = flat_tops(
        np.asarray(bottom_only.triangles), occupancy, lattice, lego_cell_height_mm=9.6
    )
    assert not np.isfinite(faces).any()
