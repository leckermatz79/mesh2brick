# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Bills of materials: CSV, BrickLink wanted-list XML, Rebrickable CSV.

Part and colour numbers in the model are LDraw numbers. BrickLink and
Rebrickable use partly different numbers (LDraw red ``4`` is BrickLink ``5``,
LDraw ``3070b`` is BrickLink ``3070``). The translation comes from
``id_maps.json``, built by ``scripts/make_id_maps.py`` from the catalogues
themselves; only confirmed mappings are used (ADR 0005). Lines without a
confirmed mapping stay in the mesh2brick CSV and are listed as a comment in
the other formats, so nothing is silently dropped or guessed.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Final
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from mesh2brick.model import BrickModel

BOM_FORMATS: Final = {
    "bom_csv": ".bom.csv",
    "bom_bricklink": ".bricklink.xml",
    "bom_rebrickable": ".rebrickable.csv",
}


@dataclass(frozen=True, slots=True)
class BomLine:
    """One part/colour line with its catalogue numbers (``None`` = unconfirmed)."""

    part: str
    description: str
    color: int
    color_name: str
    quantity: int
    bricklink_part: str | None = None
    bricklink_color: int | None = None
    rebrickable_part: str | None = None
    rebrickable_color: int | None = None

    @property
    def on_bricklink(self) -> bool:
        """Both part and colour have a confirmed BrickLink number."""
        return self.bricklink_part is not None and self.bricklink_color is not None

    @property
    def on_rebrickable(self) -> bool:
        """Both part and colour have a confirmed Rebrickable number."""
        return self.rebrickable_part is not None and self.rebrickable_color is not None


@dataclass(frozen=True, slots=True)
class Bom:
    """A model's complete parts list."""

    model: str
    lines: tuple[BomLine, ...]

    @property
    def total(self) -> int:
        """Total number of parts."""
        return sum(line.quantity for line in self.lines)

    def missing(self, catalogue: str) -> tuple[BomLine, ...]:
        """Lines without a confirmed number in ``bricklink`` or ``rebrickable``."""
        attribute = "on_bricklink" if catalogue == "bricklink" else "on_rebrickable"
        return tuple(line for line in self.lines if not getattr(line, attribute))


@dataclass(frozen=True, slots=True)
class IdMaps:
    """The parsed ``id_maps.json``."""

    parts: dict[str, dict[str, Any]]
    colors: dict[int, dict[str, Any]]
    generated: str


@lru_cache(maxsize=1)
def load_id_maps() -> IdMaps:
    """Load the bundled LDraw -> BrickLink/Rebrickable table."""
    text = (
        resources.files("mesh2brick.export")
        .joinpath("id_maps.json")
        .read_text(encoding="utf-8")
    )
    data = json.loads(text)
    return IdMaps(
        parts=dict(data["parts"]),
        colors={int(code): row for code, row in data["colors"].items()},
        generated=str(data["generated"]),
    )


COMMON_MIN_PARTS: Final = 1000
"""A common colour exists in at least this many different parts (Rebrickable)."""
COMMON_RECENT_YEARS: Final = 2
"""... and was still produced this many years before the table was made."""


_FINISH_WORDS: Final = ("silver", "gold", "copper", "bronze")
"""Metallic/pearl finishes (BrickLink files Flat Silver under "Pearl"); SPEC §2
allows them only on opt-in (``color.palette: all``)."""


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

    Based on Rebrickable's statistics in the ID table: at least
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


def build_bom(model: BrickModel, maps: IdMaps | None = None) -> Bom:
    """Count parts per (part, colour) and attach catalogue numbers."""
    maps = maps or load_id_maps()
    lines = []
    for (part, color), quantity in model.bill_of_materials().items():
        part_row = maps.parts.get(part, {})
        color_row = maps.colors.get(color, {})
        info = model.colors.get(color)
        lines.append(
            BomLine(
                part=part,
                description=str(part_row.get("description", part)),
                color=color,
                color_name=info.name.replace("_", " ")
                if info is not None
                else str(color_row.get("name", color)),
                quantity=quantity,
                bricklink_part=part_row.get("bricklink"),
                bricklink_color=color_row.get("bricklink"),
                rebrickable_part=part_row.get("rebrickable"),
                rebrickable_color=color_row.get("rebrickable"),
            )
        )
    return Bom(model=model.name, lines=tuple(lines))


# --------------------------------------------------------------------------- writers
def bom_csv(bom: Bom) -> str:
    """mesh2brick's own complete parts list (LDraw numbers plus catalogue IDs)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "ldraw_part",
            "description",
            "ldraw_color",
            "color_name",
            "quantity",
            "bricklink_part",
            "bricklink_color",
            "rebrickable_part",
            "rebrickable_color",
        ]
    )
    for line in bom.lines:
        writer.writerow(
            [
                line.part,
                line.description,
                line.color,
                line.color_name,
                line.quantity,
                _blank(line.bricklink_part),
                _blank(line.bricklink_color),
                _blank(line.rebrickable_part),
                _blank(line.rebrickable_color),
            ]
        )
    return out.getvalue()


def bricklink_xml(bom: Bom) -> str:
    """BrickLink wanted-list upload XML (``Wanted > Upload``)."""
    items = []
    for line in bom.lines:
        if not line.on_bricklink:
            continue
        items.append(
            "  <ITEM>"
            "<ITEMTYPE>P</ITEMTYPE>"
            f"<ITEMID>{escape(str(line.bricklink_part))}</ITEMID>"
            f"<COLOR>{line.bricklink_color}</COLOR>"
            f"<MINQTY>{line.quantity}</MINQTY>"
            "</ITEM>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"{_comment(bom, 'bricklink')}"
        "<INVENTORY>\n" + "\n".join(items) + "\n</INVENTORY>\n"
    )


def rebrickable_csv(bom: Bom) -> str:
    """Rebrickable parts-list import CSV (``Part,Color,Quantity``)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Part", "Color", "Quantity"])
    for line in bom.lines:
        if line.on_rebrickable:
            writer.writerow(
                [line.rebrickable_part, line.rebrickable_color, line.quantity]
            )
    # CSV has no comments: missing lines are reported by bom_warnings().
    return out.getvalue()


def write_boms(
    bom: Bom, out_dir: Path, stem: str, formats: Iterable[str]
) -> list[Path]:
    """Write the requested BOM formats; return the written paths."""
    writers = {
        "bom_csv": bom_csv,
        "bom_bricklink": bricklink_xml,
        "bom_rebrickable": rebrickable_csv,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in formats:
        if name in writers:
            path = out_dir / f"{stem}{BOM_FORMATS[name]}"
            path.write_text(writers[name](bom), encoding="utf-8")
            written.append(path)
    return written


def bom_warnings(bom: Bom, formats: Iterable[str]) -> list[str]:
    """Human-readable notes about lines a requested format cannot contain."""
    notes = []
    for name, catalogue in (
        ("bom_bricklink", "bricklink"),
        ("bom_rebrickable", "rebrickable"),
    ):
        if name not in formats:
            continue
        missing = bom.missing(catalogue)
        if missing:
            listed = ", ".join(
                f"{m.quantity}x {m.part} {m.color_name}" for m in missing
            )
            notes.append(
                f"{catalogue}: {sum(m.quantity for m in missing)} part(s) without a "
                f"confirmed {catalogue} number, left out: {listed}"
            )
    return notes


def _comment(bom: Bom, catalogue: str) -> str:
    missing = bom.missing(catalogue)
    total = bom.total - sum(m.quantity for m in missing)
    lines = [f"<!-- {bom.model}: {total} of {bom.total} parts, made by mesh2brick -->"]
    lines.extend(
        f"<!-- not included (no confirmed {catalogue} number): {m.quantity}x "
        f"LDraw {escape(m.part)} colour {m.color} {escape(m.color_name)} -->"
        for m in missing
    )
    return "\n".join(lines) + "\n"


def _blank(value: object) -> str:
    return "" if value is None else str(value)
