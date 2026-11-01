# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Small builders shared by several test modules."""

from __future__ import annotations

from mesh2brick.model import PlacedPart


def make_brick(
    part: str, x: int, y: int, layer: int, step: int, *, w: int = 2, d: int = 4
) -> PlacedPart:
    """A plain brick (3 plates tall) covering ``w`` x ``d`` studs."""
    cells = tuple(
        (x + i, y + j, layer + k) for i in range(w) for j in range(d) for k in range(3)
    )
    return PlacedPart(
        part=part, color=4, x=x, y=y, layer=layer, yaw=0, cells=cells, step=step
    )
