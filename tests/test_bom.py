# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Bills of materials and the LDraw -> BrickLink/Rebrickable ID table."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from legolization.catalog import default_catalog
from rebrickable.bom import Bom as RebrickableBom
from tests.helpers import make_brick

from mesh2brick.catalog.rebrickable import load_id_maps
from mesh2brick.export.bom import (
    BOM_FORMATS,
    bom_csv,
    bom_warnings,
    bricklink_xml,
    build_bom,
    rebrickable_csv,
    write_boms,
)
from mesh2brick.model import BrickModel, BuildStep, ColorInfo, PlacedPart


def with_colour(model: BrickModel, code: int, name: str) -> BrickModel:
    extra = PlacedPart(
        part="3001", color=code, x=9, y=9, layer=0, yaw=0, cells=((9, 9, 0),), step=0
    )
    parts = (*model.parts, extra)
    colors = {**model.colors, code: ColorInfo(name=name, rgb_hex="#000000")}
    return BrickModel(name=model.name, parts=parts, steps=model.steps, colors=colors)


# ------------------------------------------------------------------ id table
@pytest.mark.parametrize(
    ("ldraw", "bricklink", "rebrickable"),
    [(0, 11, 0), (4, 5, 4), (15, 1, 15), (71, 86, 71), (72, 85, 72), (1, 7, 1)],
)
def test_known_colour_numbers(ldraw: int, bricklink: int, rebrickable: int) -> None:
    row = load_id_maps().colors[ldraw]
    assert (row["bricklink"], row["rebrickable"]) == (bricklink, rebrickable)


def test_every_placeable_part_is_mapped() -> None:
    maps = load_id_maps()
    for part in {p.ldraw_part for p in default_catalog().parts.values()}:
        row = maps.parts[part]
        assert row["description"], part
        assert row["bricklink"], part
        assert row["rebrickable"], part


@pytest.mark.parametrize(
    ("ldraw", "bricklink", "rebrickable"),
    [("3070b", "3070", "3070b"), ("3040b", "3040", "3040b"), ("3023", "3023", "3023")],
)
def test_variant_part_numbers(ldraw: str, bricklink: str, rebrickable: str) -> None:
    row = load_id_maps().parts[ldraw]
    assert (row["bricklink"], row["rebrickable"]) == (bricklink, rebrickable)


# ------------------------------------------------------------------ bom
def test_build_bom_counts_and_maps(sample_model: BrickModel) -> None:
    bom = build_bom(sample_model)
    assert bom.total == sample_model.part_count == 3
    first = bom.lines[0]
    assert (first.part, first.quantity, first.description) == ("3001", 2, "Brick 2 x 4")
    assert (first.bricklink_part, first.bricklink_color) == ("3001", 5)
    assert (first.rebrickable_part, first.rebrickable_color) == ("3001", 4)
    assert not bom.missing("bricklink")


def test_csv_is_complete(sample_model: BrickModel) -> None:
    rows = list(csv.DictReader(io.StringIO(bom_csv(build_bom(sample_model)))))
    assert sum(int(r["quantity"]) for r in rows) == sample_model.part_count
    assert rows[0]["color_name"] == "Red"


def test_bricklink_xml_parses_with_rebrickable(sample_model: BrickModel) -> None:
    parsed = RebrickableBom.from_bricklink_xml(bricklink_xml(build_bom(sample_model)))
    assert sum(item.quantity for item in parsed.items) == sample_model.part_count
    assert {(i.part.value, i.color.value) for i in parsed.items} == {
        ("3001", 5),
        ("3003", 5),
    }


def test_rebrickable_csv_parses_with_rebrickable(sample_model: BrickModel) -> None:
    parsed = RebrickableBom.from_rebrickable_csv(
        rebrickable_csv(build_bom(sample_model))
    )
    assert sum(item.quantity for item in parsed.items) == sample_model.part_count


def test_unconfirmed_colours_are_reported_not_guessed(sample_model: BrickModel) -> None:
    model = with_colour(sample_model, 342, "Conductive Black")
    bom = build_bom(model)
    assert bom.total == 4
    assert [m.color for m in bom.missing("bricklink")] == [342]
    xml = bricklink_xml(bom)
    assert "<COLOR>342</COLOR>" not in xml
    assert "not included" in xml
    assert "3 of 4 parts" in xml
    notes = bom_warnings(bom, ["bom_bricklink", "bom_rebrickable"])
    assert any("bricklink: 1 part(s)" in n for n in notes)


def test_unknown_parts_keep_their_ldraw_number() -> None:
    model = BrickModel(
        name="x",
        parts=(make_brick("99999", 0, 0, 0, 0),),
        steps=(BuildStep(),),
    )
    line = build_bom(model).lines[0]
    assert (line.description, line.bricklink_part) == ("99999", None)


def test_write_boms(sample_model: BrickModel, tmp_path: Path) -> None:
    written = write_boms(
        build_bom(sample_model), tmp_path, "tower", ["ldr", *BOM_FORMATS]
    )
    assert [p.name for p in written] == [
        "tower.bom.csv",
        "tower.bricklink.xml",
        "tower.rebrickable.csv",
    ]


# ------------------------------------------------------------------ Phase 4
def test_acceptance_bom_shows_rebrickable_names(sample_model: BrickModel) -> None:
    """SPEC Phase 4: the parts list shows Rebrickable names."""
    bom = build_bom(sample_model)
    assert {line.name for line in bom.lines} >= {"Brick 2 x 4"}
    rows = list(csv.DictReader(io.StringIO(bom_csv(bom))))
    assert rows[0]["rebrickable_name"] == "Brick 2 x 4"
    assert rows[0]["produced_in_color"] == "yes"


def test_parts_lego_does_not_make_are_flagged(sample_model: BrickModel) -> None:
    maps = load_id_maps()
    made = set(maps.parts["3001"]["colors"])
    absent = min(c for c in maps.colors if c not in made)
    bom = build_bom(with_colour(sample_model, absent, "Odd"))
    flagged = bom.not_produced()
    assert [(line.part, line.color) for line in flagged] == [("3001", absent)]
    rows = list(csv.DictReader(io.StringIO(bom_csv(bom))))
    assert any(r["produced_in_color"] == "no" for r in rows)
    notes = bom_warnings(bom, ["bom_csv"])
    assert any("colours LEGO does not make" in n and "1x 3001 Odd" in n for n in notes)
