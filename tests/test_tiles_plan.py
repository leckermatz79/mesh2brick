# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Tile covers and the plate cells under flat tops (ROADMAP 9)."""

from __future__ import annotations

import numpy as np

from mesh2brick.place.tiles import TilePiece, flat_top_plates, tile_cover

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
