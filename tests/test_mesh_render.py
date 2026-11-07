# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Mesh pictures for ``inspect``: z-buffer rasteriser and layout (Phase 8)."""

from __future__ import annotations

import io

import numpy as np
import trimesh
from PIL import Image

from mesh2brick.render.mesh import rasterize, render_mesh_png, side_by_side
from mesh2brick.render.preview import PreviewOptions


def _png(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def test_half_square_triangle_covers_half_the_pixels() -> None:
    triangle = np.array([[[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]]])
    image = rasterize(
        triangle, np.zeros((1, 3)), np.array([[255, 0, 0]], np.uint8), 10, 10
    )
    covered = image[..., 3] > 0
    assert 45 <= covered.sum() <= 55
    assert covered[0, 0]
    assert not covered[9, 9]
    assert tuple(image[0, 0, :3]) == (255, 0, 0)


def test_nearer_triangle_wins_and_crossing_triangles_split() -> None:
    square = (
        [[0.0, 0.0], [20.0, 0.0], [0.0, 20.0]],
        [[20.0, 0.0], [20.0, 20.0], [0.0, 20.0]],
    )
    triangles = np.array([*square, *square], dtype=np.float64)
    colors = np.array([[255, 0, 0], [255, 0, 0], [0, 0, 255], [0, 0, 255]], np.uint8)
    # Red is flat at depth 0; blue tilts from -1 (left) to +1 (right).
    depth = np.array([[0, 0, 0], [0, 0, 0], [-1, 1, -1], [1, 1, -1]], dtype=np.float64)
    image = rasterize(triangles, depth, colors, 20, 20)
    assert tuple(image[10, 2, :3]) == (255, 0, 0)  # left: red is nearer
    assert tuple(image[10, 17, :3]) == (0, 0, 255)  # right: blue is nearer


def test_degenerate_and_offscreen_triangles_are_harmless() -> None:
    triangles = np.array(
        [
            [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]],  # a point
            [[-50.0, -50.0], [-40.0, -50.0], [-50.0, -40.0]],  # off screen
        ]
    )
    image = rasterize(triangles, np.zeros((2, 3)), np.zeros((2, 3), np.uint8), 8, 8)
    assert not image[..., 3].any()
    assert rasterize(
        np.zeros((0, 3, 2)), np.zeros((0, 3)), np.zeros((0, 3), np.uint8), 4, 4
    ).shape == (4, 4, 4)


def test_render_mesh_png_shows_the_model_in_its_colour() -> None:
    box = trimesh.creation.box((10, 10, 30))
    rgb = np.tile(np.array([201, 26, 9], np.uint8), (len(box.faces), 1))
    options = PreviewOptions(width_px=300, height_px=300, title="box")
    image = _png(render_mesh_png(box.vertices, box.faces, rgb, options))
    assert image.size == (300, 300)
    pixels = np.asarray(image).reshape(-1, 3).astype(int)
    reddish = (pixels[:, 0] > 120) & (pixels[:, 1] < 60) & (pixels[:, 2] < 50)
    assert reddish.sum() > 2000
    # Three visible sides get three different shades.
    assert len({tuple(p) for p in pixels[reddish] if p[0] > 150}) >= 3


def test_render_mesh_png_without_colours_and_two_sided() -> None:
    plane = trimesh.Trimesh(
        vertices=[[0, 0, 0], [10, 0, 0], [0, 10, 0]],
        faces=[[0, 2, 1]],  # facing down
    )
    options = PreviewOptions(width_px=200, height_px=200, elevation=30)
    culled = np.asarray(
        _png(render_mesh_png(plane.vertices, plane.faces, None, options))
    )
    both = np.asarray(
        _png(
            render_mesh_png(plane.vertices, plane.faces, None, options, two_sided=True)
        )
    )
    assert (culled == 255).all()  # the only face looks away: nothing drawn
    assert (both < 250).any()


def test_side_by_side_joins_images() -> None:
    def blank(width: int, height: int) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (width, height), "red").save(buffer, format="PNG")
        return buffer.getvalue()

    joined = _png(side_by_side([blank(30, 20), blank(40, 50)]))
    assert joined.size == (70, 50)
    assert joined.getpixel((10, 40)) == (255, 255, 255)  # padding below the short one
