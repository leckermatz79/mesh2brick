# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Small operations on a legolization layout shared by the finishing passes.

The tile pass (ADR 0020), the slope pass (ADR 0021) and the colour splitting
(ADR 0010) replace parts by others of a given footprint and need the same few
lookups: whether LEGO makes a part in a colour, the size of a rectangular
part, the usable rectangle parts of a family, and placing a part exactly on
given cells.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from legolization.layout import CollisionError

from mesh2brick.catalog.rebrickable import available_colors

if TYPE_CHECKING:
    from collections.abc import Callable

    from legolization.layout import Layout


def anything(_part: str, _colour: int) -> bool | None:
    """Colour availability unknown for every part (``parts.availability: report``)."""
    return None


def produced_in(part: str, colour: int) -> bool | None:
    """Whether LEGO makes ``part`` in ``colour`` (``None``: unknown)."""
    colours = available_colors(part)
    return None if colours is None else colour in colours


def rect_dims(part: Any) -> tuple[int, int, int] | None:
    """(width, length, height) of a full-rectangle part, else ``None``."""
    cells = part.occupied_cells
    xs = {c[0] for c in cells}
    ys = {c[1] for c in cells}
    zs = {c[2] for c in cells}
    if len(cells) != len(xs) * len(ys) * len(zs):
        return None
    width, length = sorted((len(xs), len(ys)))
    return (width, length, len(zs))


def place_exact(
    layout: Layout,
    key: str,
    target: frozenset[tuple[int, int, int]],
    layer: int,
    colour: int,
) -> int | None:
    """Add ``key`` so it covers exactly ``target``; its brick id or ``None``."""
    part = layout.catalog[key]
    tx = min(c[0] for c in target)
    ty = min(c[1] for c in target)
    for yaw in part.orientations:
        cells = part.cells_at(0, 0, layer, yaw)
        x = tx - min(c[0] for c in cells)
        y = ty - min(c[1] for c in cells)
        if frozenset(part.cells_at(x, y, layer, yaw)) == target:
            try:
                return layout.add(key, x, y, layer, yaw, colour).brick_id
            except CollisionError:
                return None
    return None


def rect_keys(
    layout: Layout,
    family: Any,
    height: int,
    *,
    colour: int,
    allowed: frozenset[str] | None,
    produced: Callable[[str, int], bool | None],
) -> dict[tuple[int, int], str]:
    """``(small, big)`` -> key of the usable rectangle parts of one family."""
    found: dict[tuple[int, int], str] = {}
    for key, entry in sorted(layout.catalog.parts.items()):
        dims = rect_dims(entry)
        if entry.category is not family or dims is None or dims[2] != height:
            continue
        if allowed is not None and entry.ldraw_part not in allowed:
            continue
        if produced(entry.ldraw_part, colour) is False:
            continue
        found.setdefault((dims[0], dims[1]), key)
    return found
