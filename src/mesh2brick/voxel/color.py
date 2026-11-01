# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Colour assignment for voxel grids (values are LDraw colour codes).

Modes available now:

* ``single``: every cell gets ``color.single_color``.
* ``height_bands``: the model height is split into ``len(color.bands)`` equal
  bands, bottom to top, each in its own colour - a quick way to make layers
  visible and to test multi-colour builds.

``vertex``, ``texture`` and ``cad`` (colours taken from the model) follow in
Phase 3. Whether a code is a real solid LDraw colour is checked by the
backend, which owns the palette.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np

from mesh2brick.voxel.grid import EMPTY

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from mesh2brick.config import ColorConfig

AVAILABLE_MODES: Final = frozenset({"single", "height_bands"})


def apply_colors(
    occupancy: NDArray[np.bool_], config: ColorConfig
) -> NDArray[np.int32]:
    """LDraw colour per cell (``EMPTY`` where unoccupied).

    Raises:
        ValueError: for colour modes that are not implemented yet.
    """
    color = np.full(occupancy.shape, EMPTY, dtype=np.int32)
    match config.mode:
        case "single":
            color[occupancy] = config.single_color
        case "height_bands":
            bands = np.asarray(config.bands, dtype=np.int32)
            nz = occupancy.shape[2]
            band_of_layer = np.minimum(np.arange(nz) * len(bands) // nz, len(bands) - 1)
            layer_color = bands[band_of_layer]
            color = np.where(occupancy, layer_color[None, None, :], EMPTY).astype(
                np.int32
            )
        case mode:
            msg = (
                f"color.mode {mode!r} arrives in Phase 3; "
                "use 'single' or 'height_bands'"
            )
            raise ValueError(msg)
    return color


def colors_needed(config: ColorConfig) -> tuple[int, ...]:
    """LDraw codes the configured mode can produce (for early validation)."""
    match config.mode:
        case "single":
            return (config.single_color,)
        case "height_bands":
            return tuple(dict.fromkeys(config.bands))
        case _:
            return ()
