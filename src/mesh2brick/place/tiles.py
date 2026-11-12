# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Smooth tops: which exposed parts get tiles, and which tiles (ROADMAP 9).

The arithmetic behind the tile pass (ADR 0020), free of any backend:

* :func:`tile_cover` covers the top of a part with as few tiles as possible
  (one tile of the same size if it exists).
* :func:`flat_top_plates` turns the voxel grid's flat tops into the plate
  layers the parts' tops sit in, with the height of the face.
* :func:`flat_faces` and :func:`tiled_faces` decide face by face: a face is
  tiled only when enough of its open top can be (issue #44); a face where
  only some parts could get tiles keeps all its studs instead of looking
  patchy.

The backend applies the result: a plate under a flat top becomes a tile of
the same size; a brick becomes two plates plus tiles (one plate when the face
is a plate lower), or gets tiles laid on it (the face a plate higher).
Everything else keeps its studs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from mesh2brick.place.split import choose_split

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

    from numpy.typing import NDArray

Cell = tuple[int, int, int]
Footprint = tuple[int, int]
"""``(small, big)`` side lengths in studs."""


@dataclass(frozen=True, slots=True)
class TilePiece:
    """One tile of a cover: offsets and lengths along and across the part."""

    along: int
    across: int
    length: int
    width: int

    @property
    def footprint(self) -> Footprint:
        """The tile's ``(small, big)`` size."""
        small, big = sorted((self.length, self.width))
        return (small, big)


def tile_cover(
    length: int, width: int, sizes: Collection[Footprint]
) -> tuple[TilePiece, ...] | None:
    """Fewest tiles of ``sizes`` covering a ``length`` x ``width`` top.

    Full-width strips first (a 2 x 3 top: 2 x 2 + 1 x 2 turned across), then,
    for a 2-wide top, two 1-wide rows. ``None`` if nothing fits.
    """
    small, big = sorted((length, width))
    if (small, big) in sizes:
        return (TilePiece(0, 0, length, width),)
    options: list[tuple[TilePiece, ...]] = []
    for rows in ((width,), (1,) * width) if width > 1 else ((width,),):
        pieces: list[TilePiece] = []
        across = 0
        for row in rows:
            lengths = {
                k
                for k in range(1, length + 1)
                if tuple(sorted((k, row))) in sizes  # turned either way
            }
            split = choose_split(length, lengths)
            if split is None:
                break
            along = 0
            for piece in split:
                pieces.append(TilePiece(along, across, piece, row))
                along += piece
            across += row
        else:
            options.append(tuple(pieces))
    return min(options, key=len) if options else None


def flat_top_plates(
    flat: NDArray[np.float32], plates_per_cell: int
) -> dict[tuple[int, int, int], float]:
    """Plate cells just below the flat tops of a grid, with the face's height.

    ``flat`` is :attr:`mesh2brick.voxel.grid.VoxelGrid.flat` (cell layers,
    ``NaN``: not flat). A flat cell ``(x, y, z)`` of a brick grid is topped by
    plate layer ``3 z + 2``; the value is how many plates the face lies above
    that layer's top (``-1.0``: a plate lower).
    """
    at = np.argwhere(np.isfinite(flat))
    return {
        (int(x), int(y), int(z) * plates_per_cell + plates_per_cell - 1): float(
            flat[x, y, z] * plates_per_cell
        )
        for x, y, z in at
    }


def flat_faces(cells: Iterable[Cell]) -> dict[Cell, int]:
    """Number the faces of flat plate cells: side by side within one layer.

    Cells ``(x, y, layer)`` that touch along a side and share a layer form one
    face (the faces of :mod:`mesh2brick.voxel.flat`, border cells included);
    returns the face number of every cell, numbered from 0 in sorted order.
    """
    todo = set(cells)
    face_of: dict[Cell, int] = {}
    number = -1
    for start in sorted(todo):
        if start in face_of:
            continue
        number += 1
        stack = [start]
        face_of[start] = number
        while stack:
            x, y, z = stack.pop()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                near = (nx, ny, z)
                if near in todo and near not in face_of:
                    face_of[near] = number
                    stack.append(near)
    return face_of


def tiled_faces(
    open_cells: Mapping[int, int], tileable_cells: Mapping[int, int], min_share: float
) -> frozenset[int]:
    """Faces whose tileable share of the open top reaches ``min_share``.

    ``open_cells``: per face, its cells with nothing on them; ``tileable_cells``:
    per face, those of them under parts that can get a smooth top.
    """
    return frozenset(
        face
        for face, total in open_cells.items()
        if total and tileable_cells.get(face, 0) >= min_share * total - 1e-9
    )


Column = tuple[int, int]


def rect_cover(
    columns: Collection[Column], sizes: Collection[Footprint]
) -> list[tuple[Footprint, frozenset[Column]]] | None:
    """Cover ``(x, y)`` columns exactly with rectangles of ``sizes`` (``None``: no).

    Greedy from the smallest uncovered column: it must be a corner of whatever
    rectangle covers it, so the largest size that fits there, either way
    round, is taken. Used to split a part along the edge of a flat face (issue
    #46); shapes from a straight or stepped edge are always covered when
    1 x 1 is among the sizes.
    """
    left = set(columns)
    order = sorted(sizes, key=lambda s: (-s[0] * s[1], s))
    pieces: list[tuple[Footprint, frozenset[Column]]] = []
    while left:
        x0, y0 = min(left)
        for small, big in order:
            block = next(
                (
                    cells
                    for w, h in {(small, big), (big, small)}
                    if (
                        cells := frozenset(
                            (x0 + i, y0 + j) for i in range(w) for j in range(h)
                        )
                    )
                    <= left
                ),
                None,
            )
            if block is not None:
                pieces.append(((small, big), block))
                left -= block
                break
        else:
            return None
    return pieces


def cut_band(inside: Collection[Column], outside: Collection[Column]) -> set[Column]:
    """Inside columns next to the outside ones: one stud along the cut."""
    out = set(outside)
    return {
        (x, y)
        for x, y in inside
        if {(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)} & out
    }
