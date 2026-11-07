# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Rough part count of a voxel grid before placement (``inspect``, ``convert``)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

FOOTPRINTS: Final = ((2, 8), (2, 6), (2, 4), (2, 3), (2, 2), (1, 8), (1, 6), (1, 4))
"""Brick/plate footprints (studs) for the quick fill, beside 1 x 3, 1 x 2, 1 x 1."""
ESTIMATE_FACTORS: Final = (0.9, 1.3, 2.0)
"""Placed parts per part of the quick fill (low, typical, high). Measured on
15 conversions (docs/benchmarks.md, Phase 8): 14 between 0.93 and 1.76, median
1.3. The quick fill knows neither the hollowing nor the stability repairs,
which add parts; thin wide slabs that legolization builds from plates can
need more (3.6 x for a castle courtyard)."""
MAX_FILL_CELLS: Final = 400_000
"""Bigger grids are estimated from their cell count (the fill is a Python loop)."""
CELLS_PER_PART: Final = 6.0
"""Fallback: filled cells per part of the quick fill (typical for big models)."""


def parts_estimate(occupancy: NDArray[np.bool_]) -> tuple[int, int, int]:
    """Rough ``(low, expected, high)`` part count of the converted model.

    Based on :func:`quick_fill` of the solid grid; the real placement
    hollows the model and repairs stability, which the factors cover.
    """
    filled = int(occupancy.sum())
    fill = (
        quick_fill(occupancy) if filled <= MAX_FILL_CELLS else filled / CELLS_PER_PART
    )
    low, typical, high = (max(1, round(fill * f)) for f in ESTIMATE_FACTORS)
    return low, typical, high


def quick_fill(occupancy: NDArray[np.bool_]) -> int:
    """Parts a layer-by-layer greedy fill with the largest bricks needs.

    Every layer is scanned cell by cell; the first free cell gets the largest
    footprint (either orientation) that fits into free cells. A quick stand-in
    for placement, used only for the estimate.
    """
    shapes = sorted(
        {s for w, d in (*FOOTPRINTS, (1, 3), (1, 2), (1, 1)) for s in ((w, d), (d, w))},
        key=lambda s: (-s[0] * s[1], s),
    )
    nx, ny, nz = occupancy.shape
    parts = 0
    for z in range(nz):
        free = occupancy[:, :, z].copy()
        for x, y in np.argwhere(free):
            if not free[x, y]:
                continue
            for w, d in shapes:
                if x + w <= nx and y + d <= ny and free[x : x + w, y : y + d].all():
                    free[x : x + w, y : y + d] = False
                    parts += 1
                    break
    return parts
