# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Offline catalogue data: catalogue numbers, names, colours, availability.

Everything comes from ``id_maps.json``, which ``scripts/make_id_maps.py``
builds from the catalogues themselves (BrickLink colour guide and part pages,
Rebrickable's CSV dumps) and which ships with mesh2brick, so nothing here
needs the network (ADR 0005, ADR 0009):

* LDraw -> BrickLink / Rebrickable part and colour numbers (confirmed only),
* Rebrickable part names,
* the colours each part is produced in (Rebrickable ``elements.csv``),
* Rebrickable's usage statistics per colour (the ``common`` palette).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Final

COMMON_MIN_PARTS: Final = 1000
"""A common colour exists in at least this many different parts (Rebrickable)."""
COMMON_RECENT_YEARS: Final = 2
"""... and was still produced this many years before the table was made."""
_FINISH_WORDS: Final = ("silver", "gold", "copper", "bronze")
"""Metallic/pearl finishes (BrickLink files Flat Silver under "Pearl"); SPEC §2
allows them only on opt-in (``color.palette: all``)."""


@dataclass(frozen=True, slots=True)
class IdMaps:
    """The parsed ``id_maps.json``."""

    parts: dict[str, dict[str, Any]]
    colors: dict[int, dict[str, Any]]
    generated: str


@lru_cache(maxsize=1)
def load_id_maps() -> IdMaps:
    """Load the bundled catalogue table."""
    text = (
        resources.files("mesh2brick.catalog")
        .joinpath("id_maps.json")
        .read_text(encoding="utf-8")
    )
    data = json.loads(text)
    return IdMaps(
        parts=dict(data["parts"]),
        colors={int(code): row for code, row in data["colors"].items()},
        generated=str(data["generated"]),
    )


def catalogue_colors(maps: IdMaps | None = None) -> frozenset[int]:
    """Solid LDraw colours with confirmed BrickLink *and* Rebrickable numbers.

    Every part in these colours appears in all three parts lists
    (``color.palette: solid``). Metallic-looking finishes are left out.
    """
    maps = maps or load_id_maps()
    return frozenset(
        code
        for code, row in maps.colors.items()
        if row.get("bricklink") is not None
        and row.get("rebrickable") is not None
        and not any(word in str(row.get("name", "")).lower() for word in _FINISH_WORDS)
    )


def common_colors(maps: IdMaps | None = None) -> frozenset[int]:
    """Catalogue colours LEGO currently makes in many parts (default palette).

    Based on Rebrickable's statistics in the table: at least
    ``COMMON_MIN_PARTS`` parts and produced within ``COMMON_RECENT_YEARS`` of
    the table's date. That is today's palette (Black ... Coral, about 40
    colours) without rare or discontinued colours that are hard to buy.
    """
    maps = maps or load_id_maps()
    recent = int(maps.generated[:4]) - COMMON_RECENT_YEARS
    common = set()
    for code in catalogue_colors(maps):
        usage = maps.colors[code].get("usage") or {}
        parts, last = usage.get("parts") or 0, usage.get("last_year") or 0
        if parts >= COMMON_MIN_PARTS and last >= recent:
            common.add(code)
    return frozenset(common)


def color_name(code: int, maps: IdMaps | None = None) -> str:
    """LDraw colour name with spaces (``"Light Bluish Grey"``), or the code."""
    row = (maps or load_id_maps()).colors.get(code)
    return str(row["name"]) if row else str(code)


def part_name(part: str, maps: IdMaps | None = None) -> str | None:
    """Rebrickable's name of an LDraw part (``None`` if not confirmed)."""
    name = (maps or load_id_maps()).parts.get(part, {}).get("rebrickable_name")
    return None if name is None else str(name)


def available_colors(part: str, maps: IdMaps | None = None) -> frozenset[int] | None:
    """LDraw colours ``part`` is produced in (``None``: unknown).

    From Rebrickable's elements: a part/colour pair LEGO has issued as an
    element. Unknown parts (no confirmed Rebrickable number) return ``None``.
    """
    colors = (maps or load_id_maps()).parts.get(part, {}).get("colors")
    return None if colors is None else frozenset(int(c) for c in colors)
