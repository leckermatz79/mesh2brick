# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Slopes on the stairs of tilted surfaces: which ones, best first (ROADMAP 8).

The arithmetic behind the slope pass (ADR 0021), free of any backend. The
voxelizer rates every possible slope against the input mesh
(:mod:`mesh2brick.voxel.slopes`); :func:`slope_sites` turns those ratings into
slopes to try, best first:

* a 45° slope one stud wide is a 3040b; two of them side by side, falling the
  same way on the same layer, become one 3039 (2 x 2, one part instead of
  two, and it holds both columns together);
* a 33° slope (4286) runs over two sloped columns.

The backend tries them in this order on the placed model: a site whose
columns are already taken, whose parts cannot be cut to make room, or whose
slope LEGO does not make in that colour stays a stair.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np

from mesh2brick.voxel.slopes import DIRECTIONS, MIN_GAIN_MM, RUNS

if TYPE_CHECKING:
    from numpy.typing import NDArray

Column = tuple[int, int]
SLOPE_PARTS: Final = {(1, 1): "3040b", (1, 2): "3039", (2, 1): "4286"}
"""LDraw part per ``(sloped columns along the fall, width)``: legolization's
three slopes (45° 2 x 1, 45° 2 x 2, 33° 3 x 1)."""


@dataclass(frozen=True, slots=True)
class SlopeSite:
    """One slope to try, in grid cells.

    Attributes:
        studs: the stud columns (one, or two side by side for a 3039).
        sloped: the sloped columns, in front of the studs in the direction of
            the fall (one per stud column for 45°, two for 33°).
        layer: the cell layer the slope stands on.
        direction: ``(dx, dy)`` the face falls towards.
        part: LDraw part number (:data:`SLOPE_PARTS`).
        gain: how much closer to the mesh, summed over the sloped columns (mm
            times columns).
    """

    studs: tuple[Column, ...]
    sloped: tuple[Column, ...]
    layer: int
    direction: tuple[int, int]
    part: str
    gain: float

    @property
    def columns(self) -> frozenset[Column]:
        """Every column the slope covers."""
        return frozenset((*self.studs, *self.sloped))


def slope_sites(
    gains: NDArray[np.float32], *, min_gain: float = MIN_GAIN_MM
) -> list[SlopeSite]:
    """Slopes worth trying, best first (highest total gain, ties by position).

    ``gains`` is :attr:`mesh2brick.voxel.grid.VoxelGrid.slopes`. Two 45°
    sites side by side (same layer and fall, both worth it) also appear as
    one 3039, which ranks above each of them alone.
    """
    good = np.isfinite(gains) & (gains >= min_gain)
    sites: list[SlopeSite] = []
    single: dict[tuple[int, int, int, int], float] = {}
    for x, y, z, d, k in (tuple(int(v) for v in at) for at in np.argwhere(good)):
        run = RUNS[k]
        dx, dy = DIRECTIONS[d]
        gain = float(gains[x, y, z, d, k]) * run
        sloped = tuple((x + dx * s, y + dy * s) for s in range(1, run + 1))
        sites.append(
            SlopeSite(((x, y),), sloped, z, (dx, dy), SLOPE_PARTS[run, 1], gain)
        )
        if run == 1:
            single[x, y, z, d] = gain
    for (x, y, z, d), gain in single.items():
        dx, dy = DIRECTIONS[d]
        ax, ay = (0, 1) if dx else (1, 0)  # across the fall, one way only
        other = single.get((x + ax, y + ay, z, d))
        if other is None:
            continue
        studs = ((x, y), (x + ax, y + ay))
        sloped = tuple((sx + dx, sy + dy) for sx, sy in studs)
        sites.append(
            SlopeSite(studs, sloped, z, (dx, dy), SLOPE_PARTS[1, 2], gain + other)
        )
    sites.sort(key=lambda s: (-s.gain, s.layer, s.studs, s.direction, s.part))
    return sites
