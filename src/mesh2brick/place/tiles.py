# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Smooth tops: which exposed parts get tiles, and which tiles (ROADMAP 9).

The arithmetic behind the tile pass (ADR 0020), free of any backend:

* :func:`tile_cover` covers the top of a part with as few tiles as possible
  (one tile of the same size if it exists).
* :func:`flat_top_plates` turns the voxel grid's flat tops into the plate
  layers the parts' tops sit in, with the height of the face.

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
    from collections.abc import Collection

    from numpy.typing import NDArray

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
