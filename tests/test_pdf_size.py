# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Compact step pictures for big models (Roadmap 4, ADR 0018)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

import pytest
from pypdf import PdfReader
from tests.helpers import make_brick

from mesh2brick.export.bom import build_bom
from mesh2brick.model import BrickModel, BuildStep, ColorInfo
from mesh2brick.render import pdf as pdf_module
from mesh2brick.render.pdf import (
    COMPACT_DPI,
    COMPACT_MIN_PARTS,
    PdfOptions,
    compact_steps,
    write_instructions,
)
from mesh2brick.render.preview import PreviewOptions, render_step_images

if TYPE_CHECKING:
    from pathlib import Path

RED = ColorInfo(name="Red", rgb_hex="#c91a09")
PER_LAYER = 32
"""2 x 4 bricks per layer: 8 columns x 4 rows, a 16 x 16 stud block."""
STEP_PICTURE_MAX_BYTES = 20_000
"""Upper bound for one compact step picture of the synthetic block at the
compact resolution (measured 11 kB; the pictures of 1.4 reach 33 kB)."""


def _block(parts: int, steps: int = 4) -> BrickModel:
    """A solid block of ``parts`` 2 x 4 bricks, built bottom-up in ``steps``."""
    bricks = []
    for i in range(parts):
        layer, slot = divmod(i, PER_LAYER)
        x, y = 2 * (slot % 8), 4 * (slot // 8)
        bricks.append(make_brick("3001", x, y, 3 * layer, i * steps // parts))
    return BrickModel(
        name="block",
        parts=tuple(bricks),
        steps=tuple(BuildStep(stable=True) for _ in range(steps)),
        colors={4: RED},
    )


def test_big_models_get_compact_step_pictures() -> None:
    assert not compact_steps(_block(COMPACT_MIN_PARTS - 1), PdfOptions())
    assert compact_steps(_block(COMPACT_MIN_PARTS), PdfOptions())
    assert compact_steps(_block(12), PdfOptions(compact=True))
    assert not compact_steps(_block(COMPACT_MIN_PARTS), PdfOptions(compact=False))


def test_compact_step_pictures_stay_small() -> None:
    model = _block(640, steps=20)
    size = {"width_px": 800, "height_px": 438}  # the 2-per-page frame at 110 dpi
    compact = render_step_images(
        model, PreviewOptions(**size, faded_edges=False, octree_palette=True)
    )
    full = render_step_images(model, PreviewOptions(**size))
    assert max(len(png) for png in compact) <= STEP_PICTURE_MAX_BYTES
    assert sum(len(png) for png in compact) < 0.6 * sum(len(png) for png in full)


def test_small_models_keep_the_pictures_of_1_4(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[PreviewOptions] = []
    original = pdf_module.render_step_images

    def spy(model: BrickModel, options: PreviewOptions, **kwargs: Any) -> list[bytes]:
        seen.append(options)
        return original(model, options, **kwargs)

    monkeypatch.setattr(pdf_module, "render_step_images", spy)
    model = _block(40)
    write_instructions(model, build_bom(model), tmp_path / "small.pdf", PdfOptions())
    write_instructions(
        model, build_bom(model), tmp_path / "forced.pdf", PdfOptions(compact=True)
    )
    small, forced = seen
    assert (small.faded_edges, small.octree_palette) == (True, False)
    assert (forced.faded_edges, forced.octree_palette) == (False, True)
    assert forced.width_px == pytest.approx(small.width_px * COMPACT_DPI / 130, abs=1)


@pytest.mark.parametrize("parts", [40, COMPACT_MIN_PARTS])
def test_booklets_read_back_with_pypdf(parts: int, tmp_path: Path) -> None:
    model = _block(parts)
    path = tmp_path / f"block-{parts}.pdf"
    options = PdfOptions(date=dt.date(2026, 11, 9), dpi=40)
    report = write_instructions(model, build_bom(model), path, options)
    reader = PdfReader(path)
    assert len(reader.pages) == report.pages
    assert "block" in reader.pages[0].extract_text()  # text stays text
    images = [image for page in reader.pages[2:] for image in page.images]
    assert images  # step pictures decode
