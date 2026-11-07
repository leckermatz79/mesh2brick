# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""PDF building instructions: cover, parts list with pictures, step pages.

mesh2brick's own layout (ADR 0011), drawn with reportlab on top of the
:class:`~mesh2brick.model.BrickModel`, so it needs no backend:

* **Cover:** picture of the finished model, number of parts and steps, size
  in centimetres, weight, colours and a plain-language stability verdict.
* **Parts list:** one tile per part and colour with a picture, quantity,
  name and catalogue numbers, grouped by colour.
* **Steps:** 1-4 steps per page. Each step has a call-out box with a picture
  of every new part and its quantity, a picture of the model with the new
  parts in full colour and earlier parts faded, and hints in plain words
  (hold the model, put a hanging part together with its holder first).
  Sub-assembly steps sit on a tinted panel; the step that attaches a
  sub-assembly shows it in the call-out. Steps may carry a short
  instruction text and start a titled build section (Phase 7).

Text is German or English (:mod:`mesh2brick.render.text`). The DejaVu Sans
font that ships with matplotlib is embedded, so every viewer shows the text,
umlauts included. Step pictures are palette PNGs that are embedded as they
are (no re-encoding), which keeps the file small.
"""

from __future__ import annotations

import datetime as dt
import io
import math
import struct
import time
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

import matplotlib as mpl
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfdoc, pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from mesh2brick import __version__
from mesh2brick.render.preview import (
    PreviewOptions,
    part_view_size,
    render_part_png,
    render_parts_png,
    render_png,
    render_step_images,
)
from mesh2brick.render.text import (
    Language,
    colour_label,
    mass,
    number,
    part_label,
    part_size,
    subassembly_label,
    text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mesh2brick.export.bom import Bom, BomLine
    from mesh2brick.model import BrickModel, PlacedPart

FONT: Final = "M2B-Sans"
FONT_BOLD: Final = "M2B-Sans-Bold"
_FONT_FILES: Final = {FONT: "DejaVuSans.ttf", FONT_BOLD: "DejaVuSans-Bold.ttf"}
MARGIN: Final = 36.0
FOOTER: Final = 22.0
INK: Final = HexColor("#1d1d1f")
WHITE: Final = HexColor("#ffffff")
MUTED: Final = HexColor("#6e6e73")
RULE: Final = HexColor("#d2d2d7")
CALLOUT_FILL: Final = HexColor("#f4f4f6")
SUB_FILL: Final = HexColor("#e9f1fb")
SUB_INK: Final = HexColor("#1f5fa8")
HINT_FILL: Final = HexColor("#fff4cc")
HINT_INK: Final = HexColor("#7a5a00")
WARN_FILL: Final = HexColor("#fde7e7")
CATEGORY_ORDER: Final = {"brick": 0, "plate": 1, "tile": 2, "slope": 3}
PART_PICTURE_PX: Final = (200, 150)
UNIT_PICTURE_PX: Final = (240, 180)
UNIT_ELEVATION: Final = -28.0
MAX_UNITS_SHOWN: Final = 3
STEP_TEXT_SIZE: Final = 8.5
MAX_STEP_TEXT_LINES: Final = 3
TIMES: Final = chr(0xD7)
"""Multiplication sign for quantities, as in ``3x`` with the proper sign."""


@dataclass(frozen=True, slots=True)
class PdfOptions:
    """Layout settings of the instruction booklet.

    Attributes:
        language: ``de`` or ``en``.
        page_size: ``A4`` or ``letter``.
        steps_per_page: 1-4 build steps on one page.
        dpi: resolution of the step pictures relative to the page.
        grow: frame step pictures so the model fills them while it grows
            (otherwise every picture shows the finished model's frame).
        files: file names of the parts lists for the ordering hint, keyed by
            ``bricklink`` and ``rebrickable``.
        replacements: suggested replacement per ``(part, colour)`` LEGO does
            not make, already worded in the booklet language (Phase 7,
            ``choose_part``).
        date: date printed on the cover (default: today).
        compress: compress page content (tests switch it off to read text).
    """

    language: Language = "de"
    page_size: Literal["A4", "letter"] = "A4"
    steps_per_page: int = 2
    dpi: float = 130.0
    grow: bool = True
    files: Mapping[str, str] = field(default_factory=dict)
    replacements: Mapping[tuple[str, int], str] = field(default_factory=dict)
    date: dt.date | None = None
    compress: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.steps_per_page <= 4:  # noqa: PLR2004
            msg = f"steps_per_page must be 1-4, got {self.steps_per_page}"
            raise ValueError(msg)
        if self.dpi <= 0:
            msg = f"dpi must be positive, got {self.dpi}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PdfReport:
    """What :func:`write_instructions` wrote."""

    path: Path
    pages: int
    step_pages: int
    seconds: float


@dataclass(frozen=True, slots=True)
class _Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def top(self) -> float:
        return self.y + self.h


def write_instructions(
    model: BrickModel,
    bom: Bom,
    path: Path,
    options: PdfOptions | None = None,
) -> PdfReport:
    """Write the instruction booklet for ``model`` to ``path``.

    Raises:
        ValueError: for a model without parts.
    """
    if not model.parts:
        msg = "cannot write instructions for a model without parts"
        raise ValueError(msg)
    started = time.perf_counter()
    _register_fonts()
    booklet = _Booklet(model, bom, path, options or PdfOptions())
    pages = booklet.write()
    return PdfReport(
        path=path,
        pages=pages,
        step_pages=booklet.step_pages,
        seconds=round(time.perf_counter() - started, 2),
    )


@dataclass(frozen=True, slots=True)
class _StepLayout:
    panels: tuple[_Box, ...]
    number_size: float
    tile: float

    @classmethod
    def for_page(cls, box: _Box, per_page: int) -> _StepLayout:
        gap = 14.0
        if per_page == 4:  # noqa: PLR2004
            w, h = (box.w - gap) / 2, (box.h - gap) / 2
            panels = tuple(
                _Box(box.x + col * (w + gap), box.y + (1 - row) * (h + gap), w, h)
                for row in range(2)
                for col in range(2)
            )
            return cls(panels=panels, number_size=18, tile=40)
        h = (box.h - gap * (per_page - 1)) / per_page
        panels = tuple(
            _Box(box.x, box.top - (i + 1) * h - i * gap, box.w, h)
            for i in range(per_page)
        )
        size = 24 if per_page < 3 else 20  # noqa: PLR2004
        return cls(panels=panels, number_size=size, tile=46)

    def picture(self, panel: _Box, *, bottom: float = 4.0) -> _Box:
        """Where the step picture goes inside ``panel`` (``bottom`` kept free)."""
        band = self.tile + 26
        return _Box(panel.x, panel.y + bottom, panel.w, panel.h - band - bottom - 4)


class _Booklet:
    """One instruction booklet being drawn (canvas, model and settings)."""

    def __init__(
        self, model: BrickModel, bom: Bom, path: Path, options: PdfOptions
    ) -> None:
        self.model = model
        self.bom = bom
        self.options = options
        self.lang: Language = options.language
        page_w, page_h = A4 if options.page_size == "A4" else letter
        self.page_w = page_w
        self.content = _Box(
            MARGIN, MARGIN + FOOTER, page_w - 2 * MARGIN, page_h - 2 * MARGIN - FOOTER
        )
        self.examples = _examples(model)
        self.lines = _sorted_lines(model.parts, bom, self.examples)
        self.tiles_per_page = _tiles_per_page(self.content)
        self.part_pages = self._count_part_pages()
        self.step_pages = math.ceil(model.step_count / options.steps_per_page)
        self.pages = 1 + self.part_pages + self.step_pages
        self.layout = _StepLayout.for_page(self.content, options.steps_per_page)
        self.labels = {
            name: subassembly_label(i) for i, name in enumerate(model.submodels)
        }
        self.members = _members(model)
        self._pictures: dict[tuple[str, int, str], bytes] = {}
        sizes = [part_view_size(p) for p in self.examples.values()]
        self.reference = (max(s[1] for s in sizes), max(s[3] for s in sizes))
        self._page = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        self.canvas = Canvas(
            str(path),
            pagesize=(page_w, page_h),
            pageCompression=1 if options.compress else 0,
            initialFontName=FONT,
        )
        self.canvas.setTitle(f"{model.name} - {text('instructions', self.lang)}")
        self.canvas.setAuthor("mesh2brick")
        self.canvas.setCreator(f"mesh2brick {__version__}")

    def write(self) -> int:
        """Draw every page, save the file and return the page count."""
        self.cover()
        self.finish_page()
        for index in range(self.part_pages):
            start = index * self.tiles_per_page
            self.parts_page(
                self.lines[start : start + self.tiles_per_page],
                last=index == self.part_pages - 1,
            )
            self.finish_page()
        self.step_pages_()
        self.canvas.save()
        return self._page

    def finish_page(self) -> None:
        """Footer, then a page break."""
        self._page += 1
        c = self.canvas
        c.setFillColor(MUTED)
        c.setFont(FONT, 8)
        c.drawString(MARGIN, MARGIN, self.model.name)
        c.drawRightString(
            self.page_w - MARGIN,
            MARGIN,
            text("page", self.lang, page=self._page, pages=self.pages),
        )
        c.showPage()

    def picture(self, part: str, color: int, background: Color = WHITE) -> bytes:
        """Cached picture of one part in one colour (on ``background``)."""
        key = (part, color, background.hexval())
        if key not in self._pictures:
            w, h = PART_PICTURE_PX
            self._pictures[key] = render_part_png(
                self.examples[(part, color)],
                self.model.colors.get(color),
                PreviewOptions(
                    width_px=w,
                    height_px=h,
                    margin=0.04,
                    background="#" + background.hexval()[2:],
                ),
                reference=self.reference,
            )
        return self._pictures[key]

    # ------------------------------------------------------------------ cover
    def cover(self) -> None:
        c, box, lang, model = self.canvas, self.content, self.lang, self.model
        y = box.top - 30
        c.setFillColor(INK)
        c.setFont(FONT_BOLD, 30)
        c.drawString(box.x, y, _fit(model.name, FONT_BOLD, 30, box.w))
        y -= 24
        c.setFont(FONT, 15)
        c.setFillColor(MUTED)
        c.drawString(box.x, y, text("instructions", lang))
        facts = _facts(model, lang, box.w - 110)
        notes = _cover_notes(model, lang)
        facts_h = 18 * len(facts) + 10
        notes_h = sum(_note_height(note, box.w) + 8 for note in notes)
        bottom = box.y + 36 + notes_h + facts_h
        picture = _Box(box.x, bottom, box.w, y - 16 - bottom)
        width, height = _pixels(picture.w, picture.h, self.options.dpi * 1.15)
        png = render_png(
            model, PreviewOptions(width_px=width, height_px=height, margin=0.01)
        )
        _draw_png(c, png, picture)
        y = picture.y - 22
        for label, value in facts:
            c.setFillColor(MUTED)
            c.setFont(FONT, 11)
            c.drawString(box.x, y, label)
            c.setFillColor(INK)
            c.setFont(FONT_BOLD, 11)
            c.drawString(box.x + 110, y, value)
            y -= 18
        y -= 4
        for note in notes:
            note_h = _note_height(note, box.w)
            _note(c, note, _Box(box.x, y - note_h, box.w, note_h))
            y -= note_h + 8
        today = self.options.date or dt.datetime.now(tz=dt.UTC).date()
        stamp = today.strftime("%d.%m.%Y" if lang == "de" else "%Y-%m-%d")
        c.setFillColor(MUTED)
        c.setFont(FONT, 7.5)
        c.drawString(
            box.x, box.y + 14, text("made_with", lang, version=__version__, date=stamp)
        )
        trademark = simpleSplit(text("trademark", lang), FONT, 7.5, box.w)
        for i, line in enumerate(trademark):
            c.drawString(box.x, box.y + 4 - 9 * i, line)

    # ------------------------------------------------------------------ parts
    def parts_page(self, lines: Sequence[BomLine], *, last: bool) -> None:
        c, box, lang, bom = self.canvas, self.content, self.lang, self.bom
        y = box.top - 20
        c.setFillColor(INK)
        c.setFont(FONT_BOLD, 20)
        c.drawString(box.x, y, text("parts_list", lang))
        c.setFont(FONT, 10)
        c.setFillColor(MUTED)
        total = text(
            "parts_list_total",
            lang,
            parts=number(bom.total, lang, digits=0),
            lines=len(bom.lines),
        )
        c.drawRightString(box.x + box.w, y, total)
        tile_w = box.w / _TILE_COLUMNS
        top = y - 14
        for i, line in enumerate(lines):
            row, column = divmod(i, _TILE_COLUMNS)
            self.part_tile(
                line,
                _Box(
                    box.x + column * tile_w,
                    top - (row + 1) * _TILE_HEIGHT,
                    tile_w,
                    _TILE_HEIGHT,
                ),
            )
        if not last:
            return
        y = top - math.ceil(len(lines) / _TILE_COLUMNS) * _TILE_HEIGHT - 10
        for note in self.parts_notes():
            height = _note_height(note, box.w)
            if y - height < box.y:
                break
            _note(c, note, _Box(box.x, y - height, box.w, height))
            y -= height + 8

    def _count_part_pages(self) -> int:
        """Pages for the tiles, plus one if the notes do not fit after them."""
        pages = max(1, math.ceil(len(self.lines) / self.tiles_per_page))
        rest = len(self.lines) - (pages - 1) * self.tiles_per_page
        used = _PARTS_HEADER + math.ceil(rest / _TILE_COLUMNS) * _TILE_HEIGHT + 10
        needed = sum(
            _note_height(note, self.content.w) + 8 for note in self.parts_notes()
        )
        return pages + (1 if used + needed > self.content.h else 0)

    def parts_notes(self) -> list[tuple[str, Color]]:
        lang, files = self.lang, self.options.files
        notes: list[tuple[str, Color]] = []
        if absent := self.bom.not_produced():
            listed = ", ".join(
                f"{m.quantity}{TIMES} "
                f"{part_label(self.examples[(m.part, m.color)], lang, m.name)} "
                f"{colour_label(m.color, m.color_name, lang)}"
                for m in absent
            )
            message = text("not_produced", lang, parts=listed)
            for m in absent:
                if replacement := self.options.replacements.get((m.part, m.color)):
                    original = (
                        f"{part_label(self.examples[(m.part, m.color)], lang, m.name)} "
                        f"{colour_label(m.color, m.color_name, lang)}"
                    )
                    message += " " + text(
                        "replacement", lang, part=replacement, original=original
                    )
            notes.append((message, WARN_FILL))
        if {"bricklink", "rebrickable"} <= set(files):
            shopping = text(
                "shopping",
                lang,
                bricklink=files["bricklink"],
                rebrickable=files["rebrickable"],
            )
            notes.append((shopping, CALLOUT_FILL))
        return notes

    def part_tile(self, line: BomLine, box: _Box) -> None:
        c, pad = self.canvas, 5
        picture = _Box(box.x + pad, box.top - 6 - 56, box.w - 2 * pad, 56)
        _draw_png(c, self.picture(line.part, line.color), picture, keep_aspect=True)
        y = picture.y - 12
        c.setFillColor(INK)
        c.setFont(FONT_BOLD, 11)
        c.drawString(box.x + pad, y, f"{line.quantity}{TIMES}")
        c.setFont(FONT, 7.5)
        width = box.w - 2 * pad
        name = part_label(self.examples[(line.part, line.color)], self.lang, line.name)
        names = simpleSplit(name, FONT, 7.5, width)[:2]
        for i, chunk in enumerate(names):
            c.drawString(box.x + pad, y - 10 - 9 * i, chunk)
        c.setFillColor(MUTED)
        c.setFont(FONT, 6.5)
        colour = colour_label(line.color, line.color_name, self.lang)
        details = simpleSplit(f"{line.part} · {colour}", FONT, 6.5, width)
        room = 3 - len(names)  # three text lines below the quantity
        if len(details) > room:
            details = [
                *details[: room - 1],
                _fit(" ".join(details[room - 1 :]), FONT, 6.5, width),
            ]
        for i, chunk in enumerate(reversed(details)):
            c.drawString(box.x + pad, box.y + 3 + 8 * i, chunk)

    # ------------------------------------------------------------------ steps
    def step_pages_(self) -> None:
        layout, model, per_page = self.layout, self.model, self.options.steps_per_page
        frame = layout.picture(layout.panels[0])
        width, height = _pixels(frame.w, frame.h, self.options.dpi)
        images = render_step_images(
            model,
            PreviewOptions(width_px=width, height_px=height),
            grow=self.options.grow,
            sub_background="#" + SUB_FILL.hexval()[2:],
        )
        for start in range(0, model.step_count, per_page):
            end = min(start + per_page, model.step_count)
            for slot, step in enumerate(range(start, end)):
                self.step_panel(step, images[step], layout.panels[slot])
            self.finish_page()

    def step_panel(self, step: int, image: bytes, panel: _Box) -> None:
        c, lang, layout, model = self.canvas, self.lang, self.layout, self.model
        info = model.steps[step]
        sub = info.submodel
        labels: list[tuple[str, Color]] = []
        if sub is not None:
            c.setFillColor(SUB_FILL)
            c.roundRect(panel.x, panel.y, panel.w, panel.h, 8, stroke=0, fill=1)
            labels.append((text("subassembly", lang, name=self.labels[sub]), SUB_INK))
        else:
            c.setStrokeColor(RULE)
            c.setLineWidth(0.6)
            c.line(panel.x, panel.y - 7, panel.x + panel.w, panel.y - 7)
        if info.section is not None:
            labels.append((_fit(info.section, FONT_BOLD, 10, panel.w / 3), INK))
        reserve = 6.0
        c.setFont(FONT_BOLD, 10)
        for row, (label, ink) in enumerate(labels):
            c.setFillColor(ink)
            c.drawRightString(panel.x + panel.w - 8, panel.top - 16 - 14 * row, label)
            reserve = max(reserve, pdfmetrics.stringWidth(label, FONT_BOLD, 10) + 16)
        c.setFillColor(SUB_INK if sub is not None else INK)
        c.setFont(FONT_BOLD, layout.number_size)
        c.drawString(panel.x + 6, panel.top - layout.number_size - 2, str(step + 1))
        x = panel.x + 6 + layout.number_size * 1.6 + 8
        if info.attaches is not None:
            width = layout.tile * 2.4
            caption = text("attach", lang, name=self.labels[info.attaches])
            self.attach_callout(
                self.members[info.attaches],
                _Box(x, panel.top - layout.tile - 20, width, layout.tile + 16),
                caption,
            )
            x += width + 8
        if parts := model.parts_in_step(step):
            right = panel.x + panel.w - reserve
            x = self.parts_callout(parts, x, panel.top - 4, right)
        if units := _units(model, step):
            self.unit_pictures(units, x + 8, panel)
        bottom = 4.0
        if hints := _step_hints(model, step, lang):
            note = (" ".join(hints), HINT_FILL)
            _note(c, note, _Box(panel.x + 4, panel.y + 2, panel.w - 8, 20), size=8)
            bottom = 26.0
        if info.text is not None:
            bottom = self.step_text(info.text, panel, bottom)
        _draw_png(c, image, layout.picture(panel, bottom=bottom), keep_aspect=True)

    def step_text(self, message: str, panel: _Box, bottom: float) -> float:
        """Draw a step's instruction above ``bottom``; return the new bottom."""
        c, width = self.canvas, panel.w - 16
        lines = simpleSplit(message, FONT, STEP_TEXT_SIZE, width)
        if len(lines) > MAX_STEP_TEXT_LINES:
            rest = " ".join(lines[MAX_STEP_TEXT_LINES - 1 :])
            lines = [
                *lines[: MAX_STEP_TEXT_LINES - 1],
                _fit(rest, FONT, STEP_TEXT_SIZE, width),
            ]
        leading = STEP_TEXT_SIZE * 1.3
        c.setFillColor(INK)
        c.setFont(FONT, STEP_TEXT_SIZE)
        y = panel.y + bottom + 3 + leading * (len(lines) - 1)
        for line in lines:
            c.drawString(panel.x + 8, y, line)
            y -= leading
        return bottom + leading * len(lines) + 6

    def parts_callout(
        self, parts: Sequence[PlacedPart], x: float, top: float, right: float
    ) -> float:
        """Draw the call-out box with every new part; return its right edge."""
        c, tile = self.canvas, self.layout.tile
        counts = Counter((p.part, p.color) for p in parts)
        kinds = sorted(counts, key=lambda k: (-counts[k], k))
        size = min(tile, max(right - x - 8, tile) / len(kinds))
        width, height = size * len(kinds) + 8, tile + 18
        c.setFillColor(CALLOUT_FILL)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.roundRect(x, top - height, width, height, 6, stroke=1, fill=1)
        for i, kind in enumerate(kinds):
            cell = _Box(x + 4 + i * size, top - 4 - size * 0.75, size, size * 0.75)
            _draw_png(c, self.picture(*kind, CALLOUT_FILL), cell, keep_aspect=True)
            c.setFillColor(INK)
            c.setFont(FONT_BOLD, 8 if size > 30 else 6.5)  # noqa: PLR2004
            label = f"{counts[kind]}{TIMES}"
            c.drawCentredString(cell.x + size / 2, top - height + 5, label)
        return x + width

    def attach_callout(self, indices: Sequence[int], box: _Box, caption: str) -> None:
        c = self.canvas
        c.setFillColor(SUB_FILL)
        c.setStrokeColor(SUB_INK)
        c.setLineWidth(0.8)
        c.roundRect(box.x, box.y, box.w, box.h, 6, stroke=1, fill=1)
        width, height = _pixels(box.w, box.h - 12, self.options.dpi * 1.5)
        png = render_parts_png(
            self.model,
            indices,
            PreviewOptions(width_px=width, height_px=height, margin=0.04),
        )
        inner = _Box(box.x + 2, box.y + 11, box.w - 4, box.h - 13)
        _draw_png(c, png, inner, keep_aspect=True)
        c.setFillColor(SUB_INK)
        c.setFont(FONT_BOLD, 7)
        fitted = _fit(caption, FONT_BOLD, 7, box.w - 4)
        c.drawCentredString(box.x + box.w / 2, box.y + 3, fitted)

    def unit_pictures(
        self, units: Sequence[Sequence[int]], x: float, panel: _Box
    ) -> None:
        """Small views from below of parts to put together first."""
        c, size = self.canvas, self.layout.tile + 16
        right = panel.x + panel.w - 6
        shown = list(units[:MAX_UNITS_SHOWN])
        width = size * 1.33
        if x + width * len(shown) > right:
            shown = shown[: max(1, int((right - x) // width))]
            width = min(width, (right - x) / len(shown))
        top = panel.top - 4
        for i, unit in enumerate(shown):
            box = _Box(x + i * width, top - size - 2, width - 4, size + 2)
            c.setFillColor(HINT_FILL)
            c.setStrokeColor(HINT_INK)
            c.setLineWidth(0.6)
            c.roundRect(box.x, box.y, box.w, box.h, 6, stroke=1, fill=1)
            w, h = UNIT_PICTURE_PX
            view = PreviewOptions(
                width_px=w, height_px=h, elevation=UNIT_ELEVATION, margin=0.05
            )
            png = render_parts_png(self.model, unit, view)
            inner = _Box(box.x + 2, box.y + 10, box.w - 4, box.h - 12)
            _draw_png(c, png, inner, keep_aspect=True)
            c.setFillColor(HINT_INK)
            c.setFont(FONT_BOLD, 6.5)
            c.drawCentredString(box.x + box.w / 2, box.y + 3, text("first", self.lang))


_TILE_COLUMNS: Final = 5
_TILE_HEIGHT: Final = 104.0


_PARTS_HEADER: Final = 34.0


def _tiles_per_page(box: _Box) -> int:
    rows = int((box.h - _PARTS_HEADER) // _TILE_HEIGHT)
    return max(1, rows) * _TILE_COLUMNS


def _facts(model: BrickModel, lang: Language, width: float) -> list[tuple[str, str]]:
    """Label/value pairs of the cover; values fit into ``width`` points."""
    w, d, h = (v / 10 for v in model.size_mm())
    size = text(
        "size_value", lang, w=number(w, lang), d=number(d, lang), h=number(h, lang)
    )
    facts = [
        (text("parts", lang), number(model.part_count, lang, digits=0)),
        (text("steps", lang), number(model.step_count, lang, digits=0)),
        (text("size", lang), size),
    ]
    if model.mass_g is not None:
        weight = text("weight_value", lang, value=mass(model.mass_g, lang))
        facts.append((text("weight", lang), weight))
    facts.append((text("colours", lang), _colour_summary(model, lang, width)))
    verdict = {True: "stable_yes", False: "stable_no", None: "stable_unknown"}
    facts.append((text("stability", lang), text(verdict[model.buildable], lang)))
    return facts


def _colour_summary(model: BrickModel, lang: Language, width: float) -> str:
    """``3: Red (Rot), White (Weiß), …``: most used colours that fit ``width``."""
    counts = Counter(p.color for p in model.parts)
    names = [
        colour_label(c, model.colors[c].name, lang) if c in model.colors else str(c)
        for c, _ in counts.most_common()
    ]
    summary = f"{len(names)}: {names[0]}"
    for shown, name in enumerate(names[1:], start=1):
        longer = f"{summary}, {name}"
        rest = ", …" if shown < len(names) - 1 else ""
        if pdfmetrics.stringWidth(longer + rest, FONT_BOLD, 11) > width:
            return summary + ", …"
        summary = longer
    return summary


def _cover_notes(model: BrickModel, lang: Language) -> list[tuple[str, Color]]:
    notes: list[tuple[str, Color]] = []
    if model.buildable is False:
        notes.append((text("stable_no", lang).capitalize() + ".", WARN_FILL))
    if any(step.stable is None for step in model.steps):
        notes.append((text("layer_order", lang), HINT_FILL))
    return notes


def _step_hints(model: BrickModel, step: int, lang: Language) -> list[str]:
    info = model.steps[step]
    hints = []
    if info.stable is False:
        if info.attaches is not None:
            hints.append(text("hint_hold_attach", lang))
        elif info.submodel is not None:
            hints.append(text("hint_hold_sub", lang))
        else:
            hints.append(text("hint_hold", lang))
    if info.fragile:
        hints.append(text("hint_fragile", lang))
    if _units(model, step):
        hints.append(text("hint_units", lang))
    return hints


def _units(model: BrickModel, step: int) -> list[list[int]]:
    groups: dict[int, list[int]] = {}
    for i, part in enumerate(model.parts):
        if part.step == step and part.unit is not None:
            groups.setdefault(part.unit, []).append(i)
    return [groups[key] for key in sorted(groups)]


def _members(model: BrickModel) -> dict[str, list[int]]:
    members: dict[str, list[int]] = {}
    for i, part in enumerate(model.parts):
        sub = model.steps[part.step].submodel
        if sub is not None:
            members.setdefault(sub, []).append(i)
    return members


# --------------------------------------------------------------------------- parts
def _examples(model: BrickModel) -> dict[tuple[str, int], PlacedPart]:
    examples: dict[tuple[str, int], PlacedPart] = {}
    for part in model.parts:
        examples.setdefault((part.part, part.color), part)
    return examples


def _sorted_lines(
    parts: Sequence[PlacedPart],
    bom: Bom,
    examples: Mapping[tuple[str, int], PlacedPart],
) -> list[BomLine]:
    del parts

    def key(line: BomLine) -> tuple[str, int, int, int, str]:
        example = examples[(line.part, line.color)]
        short, long, height = part_size(example)
        category = CATEGORY_ORDER.get(example.category, 9)
        return (line.color_name, category, -long * short, -height, line.part)

    return sorted(bom.lines, key=key)


# --------------------------------------------------------------------------- helpers
def _note(
    canvas: Canvas, note: tuple[str, Color], box: _Box, *, size: float = 9.5
) -> None:
    message, fill = note
    canvas.setFillColor(fill)
    canvas.setStrokeColor(fill)
    canvas.roundRect(box.x, box.y, box.w, box.h, 5, stroke=0, fill=1)
    canvas.setFillColor(INK)
    canvas.setFont(FONT, size)
    lines = simpleSplit(message, FONT, size, box.w - 16)
    leading = size * 1.25
    y = box.y + box.h / 2 + (len(lines) - 1) * leading / 2 - size * 0.35
    for line in lines:
        canvas.drawString(box.x + 8, y, line)
        y -= leading


def _note_height(note: tuple[str, Color], width: float, size: float = 9.5) -> float:
    return len(simpleSplit(note[0], FONT, size, width - 16)) * size * 1.25 + 12


def _fit(value: str, font: str, size: float, width: float) -> str:
    """``value`` shortened with an ellipsis to fit ``width``."""
    if pdfmetrics.stringWidth(value, font, size) <= width:
        return value
    while value and pdfmetrics.stringWidth(value + "…", font, size) > width:
        value = value[:-1]
    return value + "…"


def _pixels(width_pt: float, height_pt: float, dpi: float) -> tuple[int, int]:
    return max(16, round(width_pt / 72 * dpi)), max(16, round(height_pt / 72 * dpi))


def _register_fonts() -> None:
    """Embed DejaVu Sans (shipped with matplotlib) under mesh2brick's names."""
    registered = set(pdfmetrics.getRegisteredFontNames())
    folder = Path(mpl.get_data_path()) / "fonts" / "ttf"
    for name, filename in _FONT_FILES.items():
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(folder / filename)))


# --------------------------------------------------------------------------- PNG
@dataclass(frozen=True, slots=True)
class _Png:
    width: int
    height: int
    bits: int
    colour_type: int
    palette: bytes
    data: bytes


_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_PNG_CHANNELS: Final = {0: 1, 2: 3, 3: 1}
"""Colour types embedded directly: grey, RGB, palette (no alpha)."""


def _parse_png(png: bytes) -> _Png | None:
    """Pieces of a PNG that PDF can use as they are, or ``None``."""
    if not png.startswith(_PNG_SIGNATURE):
        return None
    pos = len(_PNG_SIGNATURE)
    header: tuple[int, ...] = ()
    palette = b""
    data = bytearray()
    while pos + 8 <= len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        kind = png[pos + 4 : pos + 8]
        body = png[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            data += body
        elif kind == b"tRNS":
            return None
    if not header:
        return None
    width, height, bits, colour_type, _, _, interlace = header
    if interlace or colour_type not in _PNG_CHANNELS or bits > 8:  # noqa: PLR2004
        return None
    if colour_type == 3 and not palette:  # noqa: PLR2004
        return None
    return _Png(width, height, bits, colour_type, palette, bytes(data))


class _HexString(pdfdoc.PDFObject):  # type: ignore[misc]
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def format(self, document: Any) -> bytes:  # noqa: ARG002 - reportlab API
        return b"<" + self._raw.hex().encode("ascii") + b">"


class _PngXObject(pdfdoc.PDFImageXObject):  # type: ignore[misc]
    """A PNG embedded with its own compressed data (Flate + PNG predictors)."""

    def __init__(self, name: str, png: _Png) -> None:
        super().__init__(name)
        self.width, self.height = png.width, png.height
        self._png = png

    def format(self, document: Any) -> bytes:
        png = self._png
        stream = pdfdoc.PDFStream(content=png.data)
        entries = stream.dictionary
        entries["Type"] = pdfdoc.PDFName("XObject")
        entries["Subtype"] = pdfdoc.PDFName("Image")
        entries["Width"] = png.width
        entries["Height"] = png.height
        entries["BitsPerComponent"] = png.bits
        if png.colour_type == 3:  # noqa: PLR2004
            entries["ColorSpace"] = pdfdoc.PDFArray(
                [
                    pdfdoc.PDFName("Indexed"),
                    pdfdoc.PDFName("DeviceRGB"),
                    len(png.palette) // 3 - 1,
                    _HexString(png.palette),
                ]
            )
        else:
            entries["ColorSpace"] = pdfdoc.PDFName(
                "DeviceRGB" if png.colour_type == 2 else "DeviceGray"  # noqa: PLR2004
            )
        entries["Filter"] = pdfdoc.PDFName("FlateDecode")
        entries["DecodeParms"] = pdfdoc.PDFDictionary(
            {
                "Predictor": 15,
                "Colors": _PNG_CHANNELS[png.colour_type],
                "BitsPerComponent": png.bits,
                "Columns": png.width,
            }
        )
        result: bytes = stream.format(document)
        return result


def _draw_png(
    canvas: Canvas, png: bytes, box: _Box, *, keep_aspect: bool = False
) -> None:
    """Draw ``png`` into ``box``, embedding it without re-encoding if possible."""
    parsed = _parse_png(png)
    if parsed is None:
        canvas.drawImage(
            ImageReader(io.BytesIO(png)),
            box.x,
            box.y,
            box.w,
            box.h,
            preserveAspectRatio=keep_aspect,
        )
        return
    x, y, w, h = box.x, box.y, box.w, box.h
    if keep_aspect:
        scale = min(box.w / parsed.width, box.h / parsed.height)
        w, h = parsed.width * scale, parsed.height * scale
        x, y = box.x + (box.w - w) / 2, box.y + (box.h - h) / 2
    name = f"png{zlib.crc32(png):08x}{len(png):x}"
    document = canvas._doc
    reg_name = document.getXObjectName(name)
    if reg_name not in document.idToObject:
        image = _PngXObject(name, parsed)
        canvas._setXObjects(image)
        document.Reference(image, reg_name)
        document.addForm(name, image)
    canvas.saveState()
    canvas.translate(x, y)
    canvas.scale(w, h)
    canvas._code.append(f"/{reg_name} Do")
    canvas.restoreState()
    canvas._formsinuse.append(name)
    canvas._currentPageHasImages = 1
