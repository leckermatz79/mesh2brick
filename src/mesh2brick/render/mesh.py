# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Shaded PNG of an input mesh, seen like the brick previews.

Used by ``mesh2brick inspect`` to put the model as read next to its voxels.
It uses the same orthographic camera and page layout as
:mod:`mesh2brick.render.preview`, so both pictures show the model from the
same side.

Drawing is a small vectorised z-buffer rasteriser in numpy: every triangle is
cut into pixel rows and row spans, every covered pixel centre gets the depth
of the triangle's plane, and the nearest triangle wins. Unlike sorting whole
triangles (the brick previews can, because cells sit on a lattice), this is
exact where parts interpenetrate, and its cost grows with the covered pixels,
not with the triangle count, so scans with millions of triangles need no
simplification. Faces are flat-shaded by a fixed light; the picture is
rendered at :data:`SUPERSAMPLE` times the size and downsampled (antialiasing).
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Final

import numpy as np
from PIL import Image

from mesh2brick.render.preview import (
    Camera,
    PreviewOptions,
    axes_pixels,
    draw_image_png,
    fitted_extent,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from mesh2brick.render.preview import Extent

NEUTRAL_RGB: Final = (200, 200, 200)
"""Colour of faces without colour information."""
SUPERSAMPLE: Final = 2
_LIGHT: Final = np.array([0.2, -0.35, 0.91])
"""Light direction (mostly from above), so tops, right and left sides get
about the brightness of the brick previews (1.0, 0.66, 0.74)."""
_AMBIENT: Final = 0.55
_DEGENERATE: Final = 1e-12


def render_mesh_png(
    vertices: NDArray[np.float64],
    faces: NDArray[np.int64],
    face_rgb: NDArray[np.uint8] | None,
    options: PreviewOptions | None = None,
    *,
    two_sided: bool = False,
) -> bytes:
    """Shaded orthographic picture of a triangle mesh (z up) as PNG bytes.

    Args:
        vertices: ``(V, 3)`` positions, any unit.
        faces: ``(F, 3)`` vertex indices with outward winding.
        face_rgb: ``(F, 3)`` sRGB colour per face; ``None`` draws everything
            in :data:`NEUTRAL_RGB`.
        options: size, camera angles and title (as for brick previews).
        two_sided: draw back faces too (open meshes whose winding cannot be
            trusted); otherwise faces turned away from the camera are skipped.
    """
    options = options or PreviewOptions()
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    rgb = (
        np.tile(np.asarray(NEUTRAL_RGB, dtype=np.uint8), (len(faces), 1))
        if face_rgb is None
        else np.asarray(face_rgb, dtype=np.uint8)
    )
    camera = Camera.from_angles(options.elevation, options.azimuth)
    corners = vertices[faces]  # (F, 3, 3)
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    length = np.linalg.norm(normals, axis=1)
    keep = length > 0
    if not two_sided:
        keep &= normals @ camera.toward_viewer > 0
    corners, rgb = corners[keep], rgb[keep]
    unit = normals[keep] / length[keep][:, None]
    diffuse = unit @ (_LIGHT / np.linalg.norm(_LIGHT))
    if two_sided:
        diffuse = np.abs(diffuse)
    shade = _AMBIENT + (1.0 - _AMBIENT) * np.clip(diffuse, 0.0, 1.0)
    fills = np.clip(np.rint(rgb * shade[:, None]), 0, 255).astype(np.uint8)

    screen = camera.project(corners)  # (F, 3, 2)
    depth = corners @ camera.toward_viewer  # (F, 3): larger = nearer
    bounds: Extent = (0.0, 1.0, 0.0, 1.0)
    if len(screen):
        flat = screen.reshape(-1, 2)
        low, high = flat.min(axis=0), flat.max(axis=0)
        bounds = (float(low[0]), float(high[0]), float(low[1]), float(high[1]))
    extent = fitted_extent(bounds, options)
    width, height = (n * SUPERSAMPLE for n in axes_pixels(options))
    x0, x1, y0, y1 = extent
    pixels = np.empty_like(screen)
    pixels[..., 0] = (screen[..., 0] - x0) / (x1 - x0) * width
    pixels[..., 1] = (y1 - screen[..., 1]) / (y1 - y0) * height  # rows go down
    image = rasterize(pixels, depth, fills, width, height)
    return draw_image_png(image, extent, options)


def rasterize(
    triangles: NDArray[np.float64],
    depth: NDArray[np.float64],
    colors: NDArray[np.uint8],
    width: int,
    height: int,
) -> NDArray[np.uint8]:
    """Z-buffer raster of flat-coloured triangles as an RGBA image.

    Args:
        triangles: ``(F, 3, 2)`` corner positions in pixels (x right, y down).
        depth: ``(F, 3)`` depth per corner; the largest value is in front.
        colors: ``(F, 3)`` RGB per triangle.
        width: image width in pixels.
        height: image height in pixels.

    Returns:
        ``(height, width, 4)`` RGBA; uncovered pixels are transparent.
    """
    image = np.zeros((height, width, 4), dtype=np.uint8)
    if not len(triangles):
        return image
    xs, ys = triangles[..., 0], triangles[..., 1]
    # Pixel (column c, row r) has its centre at (c + 0.5, r + 0.5).
    row_lo = np.clip(np.ceil(ys.min(axis=1) - 0.5), 0, height).astype(np.int64)
    row_hi = np.clip(np.floor(ys.max(axis=1) - 0.5), -1, height - 1).astype(np.int64)
    rows = np.maximum(row_hi - row_lo + 1, 0)
    tri = np.repeat(np.arange(len(triangles)), rows)
    row = row_lo[tri] + _ramp(rows)
    yc = row + 0.5

    # Row span: where the row's centre line crosses the triangle's edges.
    left = np.full(len(tri), np.inf)
    right = np.full(len(tri), -np.inf)
    for start, end in ((0, 1), (1, 2), (2, 0)):
        xa, ya = xs[tri, start], ys[tri, start]
        xb, yb = xs[tri, end], ys[tri, end]
        crosses = ((ya <= yc) & (yc < yb)) | ((yb <= yc) & (yc < ya))
        with np.errstate(divide="ignore", invalid="ignore"):
            x = xa + (yc - ya) * (xb - xa) / (yb - ya)
        left = np.where(crosses, np.minimum(left, x), left)
        right = np.where(crosses, np.maximum(right, x), right)
    spans = np.isfinite(left) & np.isfinite(right)
    col_lo = np.zeros(len(tri), dtype=np.int64)
    col_hi = np.full(len(tri), -1, dtype=np.int64)
    col_lo[spans] = np.clip(np.ceil(left[spans] - 0.5), 0, width)
    col_hi[spans] = np.clip(np.floor(right[spans] - 0.5), -1, width - 1)
    cols = np.maximum(col_hi - col_lo + 1, 0)
    span = np.repeat(np.arange(len(tri)), cols)
    col = col_lo[span] + _ramp(cols)
    pixel_tri = tri[span]
    pixel_row = row[span]

    # Depth from the triangle's plane z = a x + b y + c at the pixel centre.
    a, b, c = _planes(triangles, depth)
    z = a[pixel_tri] * (col + 0.5) + b[pixel_tri] * (pixel_row + 0.5) + c[pixel_tri]
    linear = pixel_row * width + col
    if not len(linear):
        return image
    order = np.lexsort((-z, linear))
    linear, pixel_tri = linear[order], pixel_tri[order]
    nearest = np.r_[True, linear[1:] != linear[:-1]]
    flat = image.reshape(-1, 4)
    flat[linear[nearest], :3] = colors[pixel_tri[nearest]]
    flat[linear[nearest], 3] = 255
    return image


def _ramp(counts: NDArray[np.int64]) -> NDArray[np.int64]:
    """``0, 1, ..., n - 1`` for every ``n`` in ``counts``, concatenated."""
    total = int(counts.sum())
    starts = np.repeat(np.cumsum(counts) - counts, counts)
    ramp: NDArray[np.int64] = np.arange(total, dtype=np.int64) - starts
    return ramp


def _planes(
    triangles: NDArray[np.float64], depth: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Coefficients of ``depth = a x + b y + c`` for every triangle."""
    x, y = triangles[..., 0], triangles[..., 1]
    ux, uy, uz = x[:, 1] - x[:, 0], y[:, 1] - y[:, 0], depth[:, 1] - depth[:, 0]
    vx, vy, vz = x[:, 2] - x[:, 0], y[:, 2] - y[:, 0], depth[:, 2] - depth[:, 0]
    det = ux * vy - uy * vx
    usable = np.abs(det) > _DEGENERATE
    safe = np.where(usable, det, 1.0)
    a = np.where(usable, (uz * vy - uy * vz) / safe, 0.0)
    b = np.where(usable, (ux * vz - uz * vx) / safe, 0.0)
    c = depth[:, 0] - a * x[:, 0] - b * y[:, 0]
    return a, b, c


def side_by_side(images: Sequence[bytes], background: str = "#ffffff") -> bytes:
    """Join PNG images left to right (top-aligned) into one PNG."""
    opened = [Image.open(io.BytesIO(data)).convert("RGB") for data in images]
    width = sum(image.width for image in opened)
    height = max(image.height for image in opened)
    canvas = Image.new("RGB", (width, height), background)
    x = 0
    for image in opened:
        canvas.paste(image, (x, 0))
        x += image.width
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
