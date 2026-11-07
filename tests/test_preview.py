# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from matplotlib.image import imread
from PIL import Image

from mesh2brick.model import BrickModel, BuildStep, ColorInfo
from mesh2brick.render.preview import (
    PreviewOptions,
    grid_to_model,
    render_grid_preview,
    render_png,
    render_preview,
    render_step_images,
    step_view,
)
from mesh2brick.voxel.grid import VoxelGrid


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


def test_grid_preview(tmp_path: Path) -> None:
    codes = np.full((3, 2, 2), -1, dtype=np.int16)
    codes[:, 0, 0] = 4
    codes[1, 1, 1] = 15
    grid = VoxelGrid.from_codes(codes)
    model = grid_to_model(grid)
    assert model.part_count == 4
    assert all(len(p.cells) == 3 and p.category == "voxel" for p in model.parts)
    path = render_grid_preview(
        grid,
        tmp_path / "grid.png",
        PreviewOptions(width_px=300, height_px=200),
        colors={4: ColorInfo("Red", "#c91a09"), 15: ColorInfo("White", "#ffffff")},
    )
    assert _pixels(path).shape[:2] == (200, 300)


def subassembly_model() -> BrickModel:
    """Step 0 main base, steps 1-2 build 'roof' on the table, step 3 attaches it."""
    from tests.helpers import make_brick  # noqa: PLC0415

    return BrickModel(
        name="house",
        parts=(
            make_brick("3001", 0, 0, 0, 0),
            make_brick("3001", 0, 0, 3, 1),
            make_brick("3003", 0, 0, 6, 2, w=2, d=2),
        ),
        steps=(
            BuildStep(),
            BuildStep(submodel="roof"),
            BuildStep(submodel="roof"),
            BuildStep(attaches="roof"),
        ),
        colors={4: ColorInfo("Red", "#c91a09")},
    )


def test_step_view_handles_subassemblies() -> None:
    model = subassembly_model()
    assert step_view(model, 0) == (frozenset({0}), frozenset({0}))
    # Building the roof on the table: only roof parts are visible.
    assert step_view(model, 1) == (frozenset({1}), frozenset({1}))
    assert step_view(model, 2) == (frozenset({1, 2}), frozenset({2}))
    # Attaching it: everything visible, the whole roof highlighted.
    assert step_view(model, 3) == (frozenset({0, 1, 2}), frozenset({1, 2}))
    with pytest.raises(ValueError, match="outside"):
        step_view(model, 4)


def test_render_step_images_one_png_per_step() -> None:
    model = subassembly_model()
    images = render_step_images(model, PreviewOptions(width_px=200, height_px=150))
    assert len(images) == model.step_count
    assert all(image.startswith(b"\x89PNG") for image in images)
    with Image.open(io.BytesIO(images[0])) as first:
        assert first.mode == "P"  # palette PNG keeps PDFs small


def test_part_pictures_share_one_scale(sample_model: BrickModel) -> None:
    from mesh2brick.render.preview import part_view_size, render_part_png  # noqa: PLC0415

    big, small = sample_model.parts[0], sample_model.parts[2]
    sizes = [part_view_size(p) for p in (big, small)]
    reference = (max(s[1] for s in sizes), max(s[3] for s in sizes))
    color = sample_model.colors[4]
    options = PreviewOptions(width_px=120, height_px=90)
    plain = render_part_png(small, color, options)
    scaled = render_part_png(small, color, options, reference=reference)
    assert plain.startswith(b"\x89PNG")
    assert scaled.startswith(b"\x89PNG")
    assert plain != scaled  # the small part is drawn smaller next to the big one


def test_growing_frames_and_sub_backgrounds(sample_model: BrickModel) -> None:
    from mesh2brick.render.preview import _grown_frame  # noqa: PLC0415

    final = (0.0, 10.0, 0.0, 5.0)
    first = _grown_frame((4.0, 6.0, 0.0, 1.0), previous=None, final=final, aspect=2.0)
    assert first[2] == 0.0  # keeps the table at the bottom
    assert first[1] - first[0] == pytest.approx(2 * (first[3] - first[2]))
    later = _grown_frame((5.0, 7.0, 0.0, 0.5), previous=first, final=final, aspect=2.0)
    assert later[1] - later[0] >= first[1] - first[0]  # never shrinks
    roof = BrickModel(
        name="r",
        parts=sample_model.parts,
        steps=(BuildStep(submodel="top"), BuildStep(attaches="top")),
        colors=sample_model.colors,
    )
    images = render_step_images(
        roof,
        PreviewOptions(width_px=80, height_px=60),
        grow=True,
        sub_background="#e9f1fb",
    )
    assert len(images) == 2


# ------------------------------------------------------------------ slopes (1.3.0)
def _slope_2x1(studs: tuple[tuple[int, int], ...] | None) -> BrickModel:
    """A 3040b (2 deep, 1 wide, one brick high), stud on the y = 1 cell."""
    from mesh2brick.model import PlacedPart  # noqa: PLC0415

    cells = tuple((0, y, z) for y in (0, 1) for z in range(3))
    part = PlacedPart(
        part="3040b", color=4, x=0, y=0, layer=0, yaw=0, cells=cells, step=0,
        category="slope", studs=studs,
    )  # fmt: skip
    return BrickModel(
        name="slope",
        parts=(part,),
        steps=(BuildStep(),),
        colors={4: ColorInfo(name="Red", rgb_hex="#c91a09")},
    )


def test_slope_wedge_falls_from_the_stud_row_to_a_half_plate_lip() -> None:
    from mesh2brick.render.preview import LIP_PLATES, _slope_faces  # noqa: PLC0415

    model = _slope_2x1(((0, 1),))
    wedge = _slope_faces(model.parts[0])
    assert wedge is not None
    sloped, faces = wedge
    assert sloped == {(0, 0, 0), (0, 0, 1), (0, 0, 2)}  # the stud cell stays a box
    top = next(f for f in faces if f.outward == (0, 0, 1))
    heights = {float(y): float(z) for _, y, z in top.corners}
    assert heights == {1.0: 3.0, 0.0: LIP_PLATES}
    assert any(f.outward == (0.0, -1.0, 0.0) for f in faces)  # the lip faces -y
    assert _slope_faces(_slope_2x1(None).parts[0]) is None  # no stud data: a box


def test_slopes_are_drawn_as_wedges() -> None:
    wedge = render_png(_slope_2x1(((0, 1),)))
    box = render_png(_slope_2x1(None))
    assert wedge != box
    pixels = np.asarray(Image.open(io.BytesIO(wedge)).convert("L"))
    flat = np.asarray(Image.open(io.BytesIO(box)).convert("L"))
    assert (pixels < 250).sum() < (flat < 250).sum()  # the cut-away corner


def test_slopes_in_three_dimensions_and_part_pictures() -> None:
    from mesh2brick.render.preview import render_part_png  # noqa: PLC0415

    model = _slope_2x1(((0, 1),))
    picture = render_part_png(model.parts[0], model.colors[4])
    assert picture.startswith(b"\x89PNG")
