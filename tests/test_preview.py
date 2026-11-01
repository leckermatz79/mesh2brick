# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from matplotlib.image import imread

from mesh2brick.model import BrickModel
from mesh2brick.render.preview import PreviewOptions, render_preview


def _pixels(path: Path) -> np.ndarray:
    return np.asarray(imread(path))


def test_renders_png_of_requested_size(
    tmp_path: Path, sample_model: BrickModel
) -> None:
    path = render_preview(
        sample_model, tmp_path / "p.png", PreviewOptions(width_px=400, height_px=300)
    )
    image = _pixels(path)
    assert image.shape[:2] == (300, 400)
    # Something red was drawn on the white background.
    red = (image[..., 0] > 0.5) & (image[..., 1] < 0.3) & (image[..., 2] < 0.3)
    assert red.sum() > 1000


def test_step_selection_draws_less(tmp_path: Path, sample_model: BrickModel) -> None:
    options = PreviewOptions(width_px=400, height_px=300, title=None)
    full = _pixels(render_preview(sample_model, tmp_path / "a.png", options))
    first = _pixels(
        render_preview(
            sample_model,
            tmp_path / "b.png",
            PreviewOptions(width_px=400, height_px=300, up_to_step=0),
        )
    )
    assert not np.array_equal(full, first)


def test_empty_selection_is_an_error(tmp_path: Path) -> None:
    empty = BrickModel(name="e", parts=(), steps=())
    with pytest.raises(ValueError, match="nothing to render"):
        render_preview(empty, tmp_path / "x.png")


def test_unknown_colour_uses_fallback(tmp_path: Path, sample_model: BrickModel) -> None:
    model = sample_model
    no_colours = BrickModel(name=model.name, parts=model.parts, steps=model.steps)
    assert render_preview(no_colours, tmp_path / "grey.png").exists()
