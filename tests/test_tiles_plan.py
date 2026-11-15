# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Tile covers and the plate cells under flat tops (ROADMAP 9)."""

from __future__ import annotations

import numpy as np

from mesh2brick.place.tiles import (
    TilePiece,
    face_groups,
    flat_faces,
    flat_top_plates,
    tile_cover,
    tiled_faces,
)

SIZES = frozenset(
    {(1, 1), (1, 2), (1, 3), (1, 4), (1, 6), (1, 8), (2, 2), (2, 4), (2, 6)}
)
"""The tiles legolization's catalogue knows (ADR 0020)."""


def test_a_tile_of_the_same_size_is_one_piece() -> None:
    assert tile_cover(4, 2, SIZES) == (TilePiece(0, 0, 4, 2),)
    assert tile_cover(1, 6, SIZES) == (TilePiece(0, 0, 1, 6),)


def test_missing_sizes_split_into_full_width_strips() -> None:
    cover = tile_cover(3, 2, SIZES)
    assert cover == (TilePiece(0, 0, 1, 2), TilePiece(1, 0, 2, 2))
    assert [p.footprint for p in cover] == [(1, 2), (2, 2)]
    eight = tile_cover(8, 2, SIZES)
    assert eight is not None
    assert [p.length for p in eight] == [4, 4]


def test_two_rows_when_no_wide_tile_fits() -> None:
    narrow = frozenset({(1, 1), (1, 2), (1, 4)})
    cover = tile_cover(4, 2, narrow)
    assert cover == (TilePiece(0, 0, 4, 1), TilePiece(0, 1, 4, 1))


def test_no_cover_without_fitting_tiles() -> None:
    assert tile_cover(3, 1, frozenset({(2, 2)})) is None


def test_flat_tops_map_to_the_top_plate_with_the_face_height() -> None:
    flat = np.full((2, 1, 3), np.nan, dtype=np.float32)
    flat[0, 0, 1] = -1 / 3  # a plate below the voxel top
    flat[1, 0, 2] = 0.0
    found = flat_top_plates(flat, 3)
    assert found.keys() == {(0, 0, 5), (1, 0, 8)}
    assert np.isclose(found[(0, 0, 5)], -1.0)
    assert found[(1, 0, 8)] == 0.0
    assert flat_top_plates(flat, 1).keys() == {(0, 0, 1), (1, 0, 2)}


def test_flat_faces_join_side_by_side_cells_of_one_layer() -> None:
    cells = [(0, 0, 2), (1, 0, 2), (3, 0, 2), (0, 0, 5), (1, 1, 2)]
    faces = flat_faces(cells)
    assert faces[(0, 0, 2)] == faces[(1, 0, 2)] == faces[(1, 1, 2)]
    assert len({faces[(0, 0, 2)], faces[(3, 0, 2)], faces[(0, 0, 5)]}) == 3


def test_a_face_is_tiled_from_the_share_on() -> None:
    open_cells = {0: 10, 1: 10, 2: 10}
    tileable = {0: 9, 1: 8, 2: 10}
    assert tiled_faces(open_cells, tileable, 0.85) == {0, 2}
    assert tiled_faces(open_cells, tileable, 0.0) == {0, 1, 2}
    assert tiled_faces({0: 20}, {0: 17}, 0.85) == {0}  # exactly 85 %


def test_equal_faces_share_a_group_whatever_their_turn() -> None:
    tower = [(x, y, 29) for x in range(3) for y in range(2)]
    turned = [(10 + y, 10 + x, 29) for x, y, _ in tower]  # a quarter turn away
    other_layer = [(20 + x, y, 20) for x, y, _ in tower]
    cells = [*tower, *turned, *other_layer]
    faces = flat_faces(cells)
    groups = face_groups(faces)
    assert groups[faces[tower[0]]] == groups[faces[turned[0]]]
    assert groups[faces[tower[0]]] != groups[faces[other_layer[0]]]


def test_equal_faces_are_tiled_together_or_not_at_all() -> None:
    open_cells = {0: 36, 1: 36, 2: 36, 3: 36, 4: 100}
    tileable = {0: 36, 1: 36, 2: 36, 3: 25, 4: 90}  # one tower below 85 %
    groups = {0: "tower", 1: "tower", 2: "tower", 3: "tower", 4: "court"}
    assert tiled_faces(open_cells, tileable, 0.85, groups) == {4}
    assert tiled_faces(open_cells, tileable, 0.85) == {0, 1, 2, 4}
