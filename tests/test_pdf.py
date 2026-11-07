# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Own PDF instructions (Phase 6): layout, languages, fonts, embedding."""

from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from PIL import Image
from tests.helpers import make_brick

from mesh2brick.export.bom import build_bom
from mesh2brick.model import BrickModel, BuildStep, ColorInfo
from mesh2brick.render import pdf as pdf_module
from mesh2brick.render.pdf import PdfOptions, write_instructions
from mesh2brick.render.text import (
    mass,
    number,
    part_label,
    subassembly_label,
    text,
)

if TYPE_CHECKING:
    from pathlib import Path

TODAY = dt.date(2026, 11, 7)


def pages_of(pdf: bytes) -> int:
    return len(re.findall(rb"/Type /Page[^s]", pdf))


def write(model: BrickModel, path: Path, **options: object) -> bytes:
    settings = PdfOptions(date=TODAY, dpi=40, **options)  # type: ignore[arg-type]
    report = write_instructions(model, build_bom(model), path, settings)
    data = path.read_bytes()
    assert report.pages == pages_of(data)
    return data


def test_booklet_has_cover_parts_list_and_step_pages(
    tmp_path: Path, sample_model: BrickModel
) -> None:
    data = write(sample_model, tmp_path / "t.pdf")
    assert data.startswith(b"%PDF")
    assert pages_of(data) == 3  # cover, parts list, 2 steps on one page
    assert b"(tower - Bauanleitung)" in data  # German title by default


def test_english_title(tmp_path: Path, sample_model: BrickModel) -> None:
    data = write(sample_model, tmp_path / "t.pdf", language="en")
    assert b"(tower - Building instructions)" in data


@pytest.mark.parametrize(("per_page", "pages"), [(1, 4), (2, 3), (3, 3), (4, 3)])
def test_steps_per_page(
    tmp_path: Path, sample_model: BrickModel, per_page: int, pages: int
) -> None:
    data = write(sample_model, tmp_path / "t.pdf", steps_per_page=per_page)
    assert pages_of(data) == pages


def test_options_are_validated() -> None:
    with pytest.raises(ValueError, match="1-4"):
        PdfOptions(steps_per_page=5)
    with pytest.raises(ValueError, match="dpi"):
        PdfOptions(dpi=0)


def test_fonts_are_embedded_and_pictures_kept_as_png(
    tmp_path: Path, sample_model: BrickModel
) -> None:
    data = write(sample_model, tmp_path / "t.pdf", compress=False)
    assert data.count(b"/FontFile2") == 2  # regular and bold DejaVu Sans subsets
    assert b"/Indexed" in data  # palette pictures embedded without re-encoding
    assert b"/Predictor 15" in data


def test_empty_models_are_rejected(tmp_path: Path) -> None:
    empty = BrickModel(name="e", parts=(), steps=())
    with pytest.raises(ValueError, match="without parts"):
        write_instructions(empty, build_bom(empty), tmp_path / "e.pdf")


def test_subassemblies_units_and_hints_render(tmp_path: Path) -> None:
    """Sub-assembly, attach, hold and pre-assembly steps all lay out."""
    base = make_brick("3001", 0, 0, 0, 0)
    top = make_brick("3003", 1, 1, 3, 1, w=2, d=2)
    hanging = replace(make_brick("3005", 4, 0, 2, 3, w=1, d=1), unit=1)
    holder = replace(make_brick("3001", 1, 0, 3, 3), unit=1)
    model = BrickModel(
        name="mixed",
        parts=(base, top, hanging, holder),
        steps=(
            BuildStep(stable=True),
            BuildStep(submodel="roof", stable=False),
            BuildStep(attaches="roof", stable=False),
            BuildStep(stable=None, fragile=True),
        ),
        colors={4: ColorInfo(name="Red", rgb_hex="#c91a09")},
        mass_g=1234.0,
        buildable=False,
    )
    data = write(model, tmp_path / "m.pdf", steps_per_page=4)
    assert pages_of(data) == 3


def test_png_parsing_falls_back_for_transparency() -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (255, 0, 0, 128)).save(buffer, format="PNG")
    assert pdf_module._parse_png(buffer.getvalue()) is None
    assert pdf_module._parse_png(b"not a png") is None
    buffer = io.BytesIO()
    Image.new("P", (4, 4)).save(buffer, format="PNG")
    parsed = pdf_module._parse_png(buffer.getvalue())
    assert parsed is not None
    assert parsed.colour_type == 3


def test_rgba_pictures_still_draw(tmp_path: Path) -> None:
    from reportlab.pdfgen.canvas import Canvas  # noqa: PLC0415

    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (255, 0, 0, 128)).save(buffer, format="PNG")
    canvas = Canvas(str(tmp_path / "x.pdf"))
    pdf_module._draw_png(canvas, buffer.getvalue(), pdf_module._Box(0, 0, 10, 10))
    canvas.save()
    assert (tmp_path / "x.pdf").stat().st_size > 0


# ------------------------------------------------------------------ text
def test_text_in_both_languages() -> None:
    assert text("parts_list", "de") == "Teileliste"
    assert text("parts_list", "en") == "Parts list"
    assert text("page", "de", page=2, pages=9) == "Seite 2 von 9"


def test_numbers_and_masses() -> None:
    assert number(25.62, "de") == "25,6"
    assert number(1234.5, "de") == "1.234,5"
    assert number(1234.5, "en") == "1,234.5"
    assert mass(893.2, "de") == "893 g"
    assert mass(1234.0, "de") == "1,2 kg"
    assert mass(1234.0, "en") == "1.2 kg"


def test_part_labels() -> None:
    brick = make_brick("3001", 0, 0, 0, 0)
    assert part_label(brick, "de") == "Stein 2 × 4"
    assert part_label(brick, "en", "Brick 2 x 4") == "Brick 2 x 4"
    assert part_label(brick, "en") == "Brick 2 × 4"
    tall = replace(brick, cells=(*brick.cells, (0, 0, 3)))
    assert part_label(tall, "de").endswith("× 1,3")
    odd = replace(brick, category="special")
    assert part_label(odd, "de") == "3001 2 × 4"


def test_subassembly_letters() -> None:
    assert [subassembly_label(i) for i in (0, 1, 25, 26, 27)] == [
        "A",
        "B",
        "Z",
        "AA",
        "AB",
    ]


def test_parts_list_notes_fit_or_get_their_own_page(
    tmp_path: Path, sample_model: BrickModel
) -> None:
    files = {"bricklink": "t.bricklink.xml", "rebrickable": "t.rebrickable.csv"}
    bom = build_bom(sample_model)
    absent = replace(
        bom, lines=tuple(replace(line, produced=False) for line in bom.lines)
    )
    options = PdfOptions(date=TODAY, dpi=40, files=files)
    report = write_instructions(sample_model, absent, tmp_path / "n.pdf", options)
    assert report.pages == 3  # the notes fit below two tiles
    full = replace(absent, lines=absent.lines * 15)  # 30 tiles fill an A4 page
    crowded = write_instructions(sample_model, full, tmp_path / "c.pdf", options)
    assert crowded.pages == 4  # cover, tiles, a page of its own for the notes, steps
