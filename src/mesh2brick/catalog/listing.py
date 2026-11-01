# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Catalogue rows for ``mesh2brick catalog``: specs plus catalogue data.

Pure functions over data the caller collects (part specs from the LDraw
geometry, the backend's placeable parts, the active whitelist and the offline
catalogue table), so listing works offline and is easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mesh2brick.catalog.parts import PartSpec, category_of, clean_description
from mesh2brick.catalog.parts import nominal_size as _nominal
from mesh2brick.catalog.rebrickable import IdMaps, load_id_maps

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


_DECORATED = ("pattern", "sticker", " with black air", "decorated")
"""Description words of printed variants (``Slope ... with ... Pattern``)."""


@dataclass(frozen=True, slots=True)
class CatalogRow:
    """One part as ``catalog list`` shows it."""

    part: str
    name: str
    category: str
    size: str
    top_studs: int | None
    placeable: bool
    enabled: bool | None
    """Allowed by the current ``parts.*`` settings (``None``: unknown)."""
    bricklink: str | None
    rebrickable: str | None
    rebrickable_name: str | None
    colors: tuple[int, ...] | None
    """LDraw colours the part is produced in (``None``: unknown)."""

    def as_json(self) -> dict[str, Any]:
        """Plain dict for ``--json`` output."""
        return {
            "part": self.part,
            "name": self.name,
            "category": self.category,
            "size": self.size,
            "top_studs": self.top_studs,
            "placeable": self.placeable,
            "enabled": self.enabled,
            "bricklink": self.bricklink,
            "rebrickable": self.rebrickable,
            "rebrickable_name": self.rebrickable_name,
            "colors": None if self.colors is None else list(self.colors),
        }


def spec_row(
    spec: PartSpec,
    *,
    placeable: bool,
    enabled: bool | None,
    maps: IdMaps | None = None,
) -> CatalogRow:
    """Row for a part whose geometry is known."""
    row = (maps or load_id_maps()).parts.get(spec.part, {})
    colors = row.get("colors")
    return CatalogRow(
        part=spec.part,
        name=spec.name,
        category=spec.category,
        size=spec.size,
        top_studs=spec.top_studs,
        placeable=placeable,
        enabled=enabled,
        bricklink=row.get("bricklink"),
        rebrickable=row.get("rebrickable"),
        rebrickable_name=row.get("rebrickable_name"),
        colors=None if colors is None else tuple(int(c) for c in colors),
    )


def library_rows(
    entries: Iterable[tuple[str, str]],
    *,
    skip: Iterable[str] = (),
    category: str | None = None,
) -> list[CatalogRow]:
    """Rows for other LDraw library parts, from their descriptions only.

    Used by ``catalog list --all``: fast (no geometry), marked not placeable.
    Sub-parts, aliases, moved parts (``~``/``=``/``_`` prefixes) and printed
    or stickered variants are left out.
    """
    skipped = set(skip)
    rows = []
    for part, description in entries:
        lowered = description.lower()
        if (
            part in skipped
            or description.startswith(("~", "=", "_"))
            or any(word in lowered for word in _DECORATED)
        ):
            continue
        kind = category_of(description, top_studs=1)
        if category is not None and kind != category:
            continue
        size = _nominal(description)
        rows.append(
            CatalogRow(
                part=part,
                name=clean_description(description),
                category=kind,
                size="-" if size is None else f"{size[0]} x {size[1]}",
                top_studs=None,
                placeable=False,
                enabled=False,
                bricklink=None,
                rebrickable=None,
                rebrickable_name=None,
                colors=None,
            )
        )
    return rows


def catalog_rows(
    specs: Mapping[str, PartSpec],
    *,
    placeable: Iterable[str],
    allowed: frozenset[str] | None,
    category: str | None = None,
    maps: IdMaps | None = None,
) -> list[CatalogRow]:
    """Rows for the placeable parts, sorted by category and size."""
    rows = [
        spec_row(
            specs[part],
            placeable=True,
            enabled=None if allowed is None else part in allowed,
            maps=maps,
        )
        for part in placeable
        if category is None or specs[part].category == category
    ]
    order = {"brick": 0, "plate": 1, "tile": 2, "slope": 3, "other": 4}
    return sorted(
        rows,
        key=lambda r: (
            order.get(r.category, 9),
            specs[r.part].width,
            specs[r.part].length,
            r.part,
        ),
    )
