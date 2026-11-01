# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Bills of materials: CSV, BrickLink wanted-list XML, Rebrickable CSV.

Part and colour numbers in the model are LDraw numbers. BrickLink and
Rebrickable use partly different numbers (LDraw red ``4`` is BrickLink ``5``,
LDraw ``3070b`` is BrickLink ``3070``). The translation, Rebrickable's part
names and the colours each part is produced in come from the offline
catalogue (:mod:`mesh2brick.catalog.rebrickable`); only confirmed mappings are
used (ADR 0005). Lines without a confirmed mapping stay in the mesh2brick CSV
and are listed as a comment in the other formats, so nothing is silently
dropped or guessed. Part/colour pairs LEGO has never produced are flagged.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from xml.sax.saxutils import escape

from mesh2brick.catalog.rebrickable import IdMaps, load_id_maps

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
    name: str | None = None
    """Rebrickable's part name (``None`` if not confirmed)."""
    produced: bool | None = None
    """Whether LEGO makes this part in this colour (Rebrickable elements);
    ``None`` if unknown."""

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

    def not_produced(self) -> tuple[BomLine, ...]:
        """Lines whose part LEGO does not make in that colour."""
        return tuple(line for line in self.lines if line.produced is False)

    def missing(self, catalogue: str) -> tuple[BomLine, ...]:
        """Lines without a confirmed number in ``bricklink`` or ``rebrickable``."""
        attribute = "on_bricklink" if catalogue == "bricklink" else "on_rebrickable"
        return tuple(line for line in self.lines if not getattr(line, attribute))


def build_bom(model: BrickModel, maps: IdMaps | None = None) -> Bom:
    """Count parts per (part, colour) and attach catalogue numbers."""
    maps = maps or load_id_maps()
    lines = []
    for (part, color), quantity in model.bill_of_materials().items():
        part_row = maps.parts.get(part, {})
        color_row = maps.colors.get(color, {})
        info = model.colors.get(color)
        produced_in = part_row.get("colors")
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
                name=part_row.get("rebrickable_name"),
                produced=None if produced_in is None else color in produced_in,
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
            "rebrickable_name",
            "produced_in_color",
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
                _blank(line.name),
                "" if line.produced is None else ("yes" if line.produced else "no"),
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
    """Human-readable notes about the parts list.

    Parts LEGO does not make in their colour, and lines a requested format
    cannot contain.
    """
    notes = []
    if absent := bom.not_produced():
        listed = ", ".join(f"{m.quantity}x {m.part} {m.color_name}" for m in absent)
        notes.append(
            f"{sum(m.quantity for m in absent)} part(s) in colours LEGO does not "
            f"make them in (Rebrickable); substitute by hand: {listed}"
        )
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
