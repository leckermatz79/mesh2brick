# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""PNG previews and step images of a :class:`~mesh2brick.model.BrickModel`.

A small orthographic painter's-algorithm renderer on top of matplotlib's 2-D
``PolyCollection``, vectorised with numpy. Every occupied grid cell
(1 x 1 stud x 1 plate) contributes its exposed, camera-facing faces, dark
strips along part boundaries, and a stud on open tops. All polygons are drawn
back to front by cell depth; because all cells are translates of one box on a
lattice, that order is exact - unlike matplotlib's own 3-D mode.

Used for self-checks, STATUS reports and as instruction images in the PDF
(no external LDraw renderer needed). Slopes are drawn as their bounding cells.
Only matplotlib's object-oriented API is used (no ``pyplot``).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import PolyCollection
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure
from PIL import Image

from mesh2brick.model import BrickModel, BuildStep, ColorInfo, PlacedPart
from mesh2brick.voxel.grid import LDU_PER_PLATE, LDU_PER_STUD

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from numpy.typing import NDArray

    from mesh2brick.voxel.grid import VoxelGrid

STUDS_PER_PLATE: Final = LDU_PER_PLATE / LDU_PER_STUD  # cell height: 0.4 studs
STUD_RADIUS: Final = 0.3  # 4.8 mm stud diameter / 8 mm pitch
STUD_HEIGHT: Final = 0.21  # 1.7 mm / 8 mm
_EDGE_WIDTH: Final = 0.035  # boundary strip width in studs
_STUD_SEGMENTS: Final = 16
_FALLBACK_RGB: Final = "#9ba19d"
_GHOST_MIX: Final = 0.72
_EDGE_DARKEN: Final = 0.35
_FACING_EPS: Final = 1e-9
_DPI: Final = 100
STEP_IMAGE_COLORS: Final = 64
"""Palette size for step images: flat shading needs few colours, and a
palette PNG is ~3x smaller, which keeps big instruction PDFs small."""
_NO_STUD_CATEGORIES: Final = frozenset({"tile", "slope", "voxel"})
_SCALE: Final = np.array([1.0, 1.0, STUDS_PER_PLATE])

# Face normal -> brightness (fake directional light).
_DIRECTIONS: Final[tuple[tuple[tuple[int, int, int], float], ...]] = (
    ((0, 0, 1), 1.0),
    ((0, 0, -1), 0.45),
    ((1, 0, 0), 0.66),
    ((-1, 0, 0), 0.82),
    ((0, 1, 0), 0.9),
    ((0, -1, 0), 0.74),
)
_BOTTOM_SHADE_FROM_BELOW: Final = 0.86
"""Undersides are lit when the camera looks from below (pre-assembly views)."""
MIN_FRAME_SHARE: Final = 0.25
"""Growing step frames start at this share of the finished model's frame."""
PART_MIN_SHARE: Final = 0.55
"""Smallest scale of a part picture relative to the largest part."""
_STUD_SIDE_SHADE: Final = 0.62
_STUD_TOP_SHADE: Final = 1.08

Extent = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class PreviewOptions:
    """View settings for :func:`render_preview`."""

    width_px: int = 1200
    height_px: int = 900
    elevation: float = 30.0
    """Camera elevation above the ground plane, degrees."""
    azimuth: float = -60.0
    """Camera azimuth, degrees (matplotlib convention: -90 looks along +y)."""
    title: str | None = None
    margin: float = 0.02
    """Blank border around the drawing, as a share of the image size."""
    up_to_step: int | None = None
    """Show the model as built after this 0-based step (see :func:`step_view`):
    that step in full colour, earlier parts faded. ``None`` = finished model."""
    background: str = "#ffffff"


@dataclass(frozen=True, slots=True)
class Camera:
    """Orthographic camera: screen axes and the direction towards the viewer."""

    right: NDArray[np.float64]
    up: NDArray[np.float64]
    toward_viewer: NDArray[np.float64]

    @classmethod
    def from_angles(cls, elevation: float, azimuth: float) -> Camera:
        """Camera at ``elevation``/``azimuth`` degrees (see PreviewOptions)."""
        elev, azim = math.radians(elevation), math.radians(azimuth)
        toward = np.array(
            [
                math.cos(elev) * math.cos(azim),
                math.cos(elev) * math.sin(azim),
                math.sin(elev),
            ]
        )
        right = np.array([-math.sin(azim), math.cos(azim), 0.0])
        return cls(right=right, up=np.cross(toward, right), toward_viewer=toward)

    def project(self, points: NDArray[np.float64]) -> NDArray[np.float64]:
        """World points ``(..., 3)`` (studs) -> screen ``(..., 2)``."""
        return np.stack([points @ self.right, points @ self.up], axis=-1)


# --------------------------------------------------------------------------- API
def render_preview(
    model: BrickModel,
    path: Path,
    options: PreviewOptions | None = None,
) -> Path:
    """Render ``model`` to a PNG file at ``path`` and return the path.

    Raises:
        ValueError: if the model (or the step selection) has no parts.
    """
    options = options or PreviewOptions()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_png(model, options))
    return path


def render_png(
    model: BrickModel,
    options: PreviewOptions | None = None,
    *,
    extent: Extent | None = None,
) -> bytes:
    """Render ``model`` (or one build step of it) and return PNG bytes.

    ``extent`` fixes the visible screen window, so a series of step images
    keeps the model in place; by default it fits the drawn parts.

    Raises:
        ValueError: if nothing is visible.
    """
    options = options or PreviewOptions()
    if options.up_to_step is None:
        visible = frozenset(range(model.part_count))
        highlight: frozenset[int] | None = None
    else:
        visible, highlight = step_view(model, options.up_to_step)
    if not visible:
        msg = "nothing to render: the model (or step selection) has no parts"
        raise ValueError(msg)
    camera = Camera.from_angles(options.elevation, options.azimuth)
    polygons, fills = _scene(model, visible, highlight, camera, options.background)
    return draw_png(polygons, fills, options, extent)


def render_parts_png(
    model: BrickModel,
    indices: Sequence[int],
    options: PreviewOptions | None = None,
) -> bytes:
    """Render only the parts ``model.parts[i]`` for ``i`` in ``indices``.

    Raises:
        ValueError: if ``indices`` is empty.
    """
    if not indices:
        msg = "nothing to render: no parts selected"
        raise ValueError(msg)
    options = options or PreviewOptions()
    camera = Camera.from_angles(options.elevation, options.azimuth)
    polygons, fills = _scene(
        model, frozenset(indices), None, camera, options.background
    )
    return _palette_png(draw_png(polygons, fills, options, None))


def render_part_png(
    part: PlacedPart,
    color: ColorInfo | None,
    options: PreviewOptions | None = None,
    *,
    reference: tuple[float, float] | None = None,
    min_share: float = PART_MIN_SHARE,
) -> bytes:
    """Render one part on its own, long side to the right, for parts lists.

    The part is moved to the origin and turned so its longer side runs along
    ``x``; its studs face up. With ``reference`` (the largest
    :func:`part_view_size` of a set of parts) all pictures share one scale,
    except that parts smaller than ``min_share`` of the reference are
    enlarged to that share, so a 1 x 1 plate stays recognisable next to a
    2 x 8 brick.
    """
    options = options or PreviewOptions()
    model = _part_alone(part, color)
    if reference is None:
        return render_parts_png(model, [0], options)
    camera = Camera.from_angles(options.elevation, options.azimuth)
    x0, x1, y0, y1 = _screen_bounds(model.parts, camera)
    width, height = reference
    share = max((x1 - x0) / width, (y1 - y0) / height, min_share)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w, half_h = share * width / 2 * 1.04, share * height / 2 * 1.04
    extent = _fit_aspect(
        (cx - half_w, cx + half_w, cy - half_h, cy + half_h), _axes_aspect(options)
    )
    return _palette_png(render_png(model, options, extent=extent))


def part_view_size(part: PlacedPart, options: PreviewOptions | None = None) -> Extent:
    """Screen width and height (in studs) of a part as :func:`render_part_png` draws it.

    Returned as ``(0, width, 0, height)`` so it can be combined with ``max``.
    """
    options = options or PreviewOptions()
    camera = Camera.from_angles(options.elevation, options.azimuth)
    x0, x1, y0, y1 = _screen_bounds(_part_alone(part, None).parts, camera)
    return (0.0, x1 - x0, 0.0, y1 - y0)


def _part_alone(part: PlacedPart, color: ColorInfo | None) -> BrickModel:
    """``part`` alone at the origin, its longer side along ``x``."""
    xs, ys, zs = zip(*part.cells, strict=True)
    x0, y0, z0 = min(xs), min(ys), min(zs)
    swap = max(ys) - y0 > max(xs) - x0
    cells = tuple(
        (y - y0, x - x0, z - z0) if swap else (x - x0, y - y0, z - z0)
        for x, y, z in part.cells
    )
    alone = PlacedPart(
        part=part.part,
        color=part.color,
        x=0,
        y=0,
        layer=0,
        yaw=0,
        cells=cells,
        step=0,
        category=part.category,
    )
    return BrickModel(
        name=part.part,
        parts=(alone,),
        steps=(BuildStep(),),
        colors={part.color: color} if color is not None else {},
    )


def step_view(model: BrickModel, step: int) -> tuple[frozenset[int], frozenset[int]]:
    """Which parts are visible / newly placed after build step ``step``.

    A subassembly step shows only that subassembly (built on the table); a
    main-model step shows the main model plus every subassembly attached so
    far; an attach step highlights the whole attached subassembly.

    Raises:
        ValueError: for a step outside the model.
    """
    if not 0 <= step < model.step_count:
        msg = f"step {step} outside 0..{model.step_count - 1}"
        raise ValueError(msg)
    steps = model.steps
    current = steps[step]
    if current.submodel is not None:
        visible = {
            i
            for i, p in enumerate(model.parts)
            if p.step <= step and steps[p.step].submodel == current.submodel
        }
        return frozenset(visible), frozenset(
            i for i in visible if model.parts[i].step == step
        )
    attached = {s.attaches for s in steps[: step + 1] if s.attaches is not None}
    visible = {
        i
        for i, p in enumerate(model.parts)
        if p.step <= step
        and (steps[p.step].submodel is None or steps[p.step].submodel in attached)
    }
    if current.attaches is not None:
        new = {
            i
            for i in visible
            if steps[model.parts[i].step].submodel == current.attaches
        }
    else:
        new = {i for i in visible if model.parts[i].step == step}
    return frozenset(visible), frozenset(new)


def render_step_images(
    model: BrickModel,
    options: PreviewOptions | None = None,
    *,
    grow: bool = False,
    sub_background: str | None = None,
) -> list[bytes]:
    """One PNG per build step.

    By default main-model steps are framed like the finished model and
    subassembly steps like the finished subassembly, so nothing jumps
    around between pages. With ``grow`` the frame follows the model as it
    grows (never shrinking, starting at :data:`MIN_FRAME_SHARE` of the
    final frame), so early steps are shown larger. ``sub_background``
    replaces the background colour of subassembly steps.
    """
    options = options or PreviewOptions()
    camera = Camera.from_angles(options.elevation, options.azimuth)
    aspect = _axes_aspect(options)
    frames: dict[str | None, Extent] = {
        None: _fit_aspect(_fit_extent(_screen_bounds(model.parts, camera)), aspect)
    }
    for name in model.submodels:
        members = [p for p in model.parts if model.steps[p.step].submodel == name]
        frames[name] = _fit_aspect(_fit_extent(_screen_bounds(members, camera)), aspect)
    current: dict[str | None, Extent] = {}
    images: list[bytes] = []
    for step in range(model.step_count):
        context = model.steps[step].submodel
        extent = frames[context]
        visible, highlight = step_view(model, step)
        if grow and visible:
            seen = [model.parts[i] for i in visible]
            extent = _grown_frame(
                _fit_extent(_screen_bounds(seen, camera)),
                previous=current.get(context),
                final=extent,
                aspect=aspect,
            )
            current[context] = extent
        view = options
        if context is not None and sub_background is not None:
            view = replace(options, background=sub_background)
        if not visible:  # an empty step (should not happen) gets a blank frame
            images.append(draw_png([], [], view, extent))
            continue
        polygons, fills = _scene(model, visible, highlight, camera, view.background)
        images.append(_palette_png(draw_png(polygons, fills, view, extent)))
    return images


def _palette_png(png: bytes, colors: int = STEP_IMAGE_COLORS) -> bytes:
    """Re-encode an RGB(A) PNG with a small colour palette."""
    with Image.open(io.BytesIO(png)) as image:
        quantized = image.convert("RGB").quantize(
            colors=colors, method=Image.Quantize.MEDIANCUT
        )
    buffer = io.BytesIO()
    quantized.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_grid_preview(
    grid: VoxelGrid,
    path: Path,
    options: PreviewOptions | None = None,
    colors: dict[int, ColorInfo] | None = None,
) -> Path:
    """Render a voxel grid (each cell as its own block, no studs) to PNG.

    Raises:
        ValueError: if the grid is empty.
    """
    return render_preview(grid_to_model(grid, colors), path, options)


def grid_to_model(
    grid: VoxelGrid, colors: dict[int, ColorInfo] | None = None
) -> BrickModel:
    """Wrap every occupied cell as a one-cell part so it can be rendered."""
    per_cell = grid.plates_per_cell
    parts = tuple(
        PlacedPart(
            part="voxel",
            color=int(grid.color[x, y, z]),
            x=int(x),
            y=int(y),
            layer=int(z) * per_cell,
            yaw=0,
            cells=tuple(
                (int(x), int(y), int(z) * per_cell + k) for k in range(per_cell)
            ),
            step=0,
            category="voxel",
        )
        for x, y, z in np.argwhere(grid.occupancy)
    )
    return BrickModel(
        name="voxels",
        parts=parts,
        steps=(BuildStep(),) if parts else (),
        colors=dict(colors or {}),
    )


# --------------------------------------------------------------------------- scene
def _scene(
    model: BrickModel,
    visible: frozenset[int],
    highlight: frozenset[int] | None,
    camera: Camera,
    background: str,
) -> tuple[list[NDArray[np.float64]], NDArray[np.float64]]:
    """Back-to-front polygons (screen space) and their RGB fills."""
    index = np.fromiter(sorted(visible), dtype=np.int64)
    cells, owner_of_cell = _cells(model, index)
    base = _part_colours(model, index, highlight, background)
    studded = np.array(
        [model.parts[i].category not in _NO_STUD_CATEGORIES for i in index]
    )
    low = cells.min(axis=0) - 1
    shape = cells.max(axis=0) - low + 2
    owner = np.full(tuple(int(n) for n in shape), -1, dtype=np.int64)
    local = cells - low
    owner[local[:, 0], local[:, 1], local[:, 2]] = owner_of_cell  # position in index
    occupied = owner >= 0
    view = camera.toward_viewer

    groups_poly: list[NDArray[np.float64]] = []
    groups_rgb: list[NDArray[np.float64]] = []
    groups_key: list[NDArray[np.float64]] = []
    groups_order: list[NDArray[np.int64]] = []

    for direction, shade in _facing_shades(view):
        d = np.array(direction)
        exposed = occupied & ~np.roll(occupied, shift=-d, axis=(0, 1, 2))
        at = np.argwhere(exposed)
        if not len(at):
            continue
        part_pos = owner[at[:, 0], at[:, 1], at[:, 2]]
        world = (at + low).astype(np.float64)
        depth = (world * _SCALE) @ view
        corners = _face_corners(world, d) * _SCALE
        groups_poly.append(camera.project(corners))
        groups_rgb.append(np.clip(base[part_pos] * shade, 0.0, 1.0))
        groups_key.append(depth)
        groups_order.append(np.zeros(len(at), dtype=np.int64))
        for strip, keep in _strips(at, d, corners, owner, exposed):
            groups_poly.append(camera.project(strip))
            groups_rgb.append(base[part_pos[keep]] * _EDGE_DARKEN)
            groups_key.append(depth[keep])
            groups_order.append(np.ones(int(keep.sum()), dtype=np.int64))
        if direction == (0, 0, 1):
            with_stud = studded[part_pos]
            if with_stud.any():
                centres = (world[with_stud] + np.array([0.5, 0.5, 1.0])) * _SCALE
                for template, shade_stud, order in _stud_templates(camera):
                    screen = camera.project(centres)[:, None, :] + template[None]
                    groups_poly.append(screen)
                    groups_rgb.append(
                        np.clip(base[part_pos[with_stud]] * shade_stud, 0.0, 1.0)
                    )
                    groups_key.append(depth[with_stud])
                    groups_order.append(np.full(int(with_stud.sum()), order))

    if not groups_poly:
        return [], np.zeros((0, 3))
    keys = np.concatenate(groups_key)
    orders = np.concatenate(groups_order)
    rgb = np.concatenate(groups_rgb)
    flat: list[NDArray[np.float64]] = [poly for group in groups_poly for poly in group]
    permutation = np.lexsort((orders, keys))
    return [flat[i] for i in permutation], rgb[permutation]


def _facing_shades(
    view: NDArray[np.float64],
) -> list[tuple[tuple[int, int, int], float]]:
    """Face directions the camera sees, with their brightness."""
    below = float(view[2]) < 0
    return [
        (direction, _BOTTOM_SHADE_FROM_BELOW if below and direction[2] < 0 else shade)
        for direction, shade in _DIRECTIONS
        if float(np.dot(np.array(direction), view)) > _FACING_EPS
    ]


def _cells(
    model: BrickModel, index: NDArray[np.int64]
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """All cells of the selected parts and, per cell, its part's position."""
    chunks = [np.asarray(model.parts[i].cells, dtype=np.int64) for i in index]
    owners = [np.full(len(c), pos, dtype=np.int64) for pos, c in enumerate(chunks)]
    return np.concatenate(chunks), np.concatenate(owners)


def _part_colours(
    model: BrickModel,
    index: NDArray[np.int64],
    highlight: frozenset[int] | None,
    background: str,
) -> NDArray[np.float64]:
    cache: dict[int, tuple[float, float, float]] = {}
    rows = []
    for i in index:
        code = model.parts[i].color
        if code not in cache:
            info = model.colors.get(code)
            cache[code] = to_rgb(info.rgb_hex if info is not None else _FALLBACK_RGB)
        rows.append(cache[code])
    base = np.asarray(rows, dtype=np.float64)
    if highlight is not None:
        faded = np.array([i not in highlight for i in index])
        bg = np.asarray(to_rgb(background))
        base[faded] = base[faded] * (1 - _GHOST_MIX) + bg * _GHOST_MIX
    return base


def _face_corners(
    world: NDArray[np.float64], normal: NDArray[np.int_]
) -> NDArray[np.float64]:
    """``(n, 4, 3)`` corners (unit-cell space) of the faces along ``normal``."""
    axis = int(np.flatnonzero(normal)[0])
    u_axis, v_axis = [a for a in range(3) if a != axis]
    offsets = np.zeros((4, 3))
    if normal[axis] > 0:
        offsets[:, axis] = 1.0
    offsets[1, u_axis] = offsets[2, u_axis] = 1.0
    offsets[2, v_axis] = offsets[3, v_axis] = 1.0
    result: NDArray[np.float64] = world[:, None, :] + offsets[None]
    return result


def _strips(
    at: NDArray[np.int64],
    normal: NDArray[np.int_],
    corners: NDArray[np.float64],
    owner: NDArray[np.int64],
    exposed: NDArray[np.bool_],
) -> list[tuple[NDArray[np.float64], NDArray[np.bool_]]]:
    """Dark strips along face edges that are part boundaries or creases."""
    axis = int(np.flatnonzero(normal)[0])
    u_axis, v_axis = [a for a in range(3) if a != axis]
    # Corners 0-1-2-3; edge (0,1) lies at v=0, (1,2) at u=1, (2,3) at v=1, (3,0) at u=0.
    edges = (
        ((0, 1), v_axis, -1),
        ((1, 2), u_axis, 1),
        ((2, 3), v_axis, 1),
        ((3, 0), u_axis, -1),
    )
    own = owner[at[:, 0], at[:, 1], at[:, 2]]
    result = []
    for (a, b), step_axis, sign in edges:
        delta = np.zeros(3, dtype=np.int64)
        delta[step_axis] = sign
        beside = at + delta
        continues = (owner[beside[:, 0], beside[:, 1], beside[:, 2]] == own) & exposed[
            beside[:, 0], beside[:, 1], beside[:, 2]
        ]
        keep = ~continues
        if not keep.any():
            continue
        inward = -delta.astype(np.float64) * _EDGE_WIDTH
        p, q = corners[keep, a], corners[keep, b]
        result.append((np.stack([p, q, q + inward, p + inward], axis=1), keep))
    return result


def _stud_templates(
    camera: Camera,
) -> list[tuple[NDArray[np.float64], float, int]]:
    """Screen-space stud polygons relative to the stud's base centre."""
    angles = np.linspace(0.0, 2 * math.pi, _STUD_SEGMENTS, endpoint=False)
    ring = np.stack(
        [
            np.cos(angles) * STUD_RADIUS,
            np.sin(angles) * STUD_RADIUS,
            np.zeros_like(angles),
        ],
        axis=-1,
    )
    bottom = camera.project(ring)
    top = camera.project(ring + np.array([0.0, 0.0, STUD_HEIGHT]))
    side = _convex_hull(np.concatenate([bottom, top]))
    # Pad the hull to the ring length so all studs stack into one array.
    side = _resample_closed(side, _STUD_SEGMENTS * 2)
    top = _resample_closed(top, _STUD_SEGMENTS * 2)
    return [(side, _STUD_SIDE_SHADE, 2), (top, _STUD_TOP_SHADE, 3)]


def _resample_closed(polygon: NDArray[np.float64], count: int) -> NDArray[np.float64]:
    """Repeat vertices so a polygon has exactly ``count`` points (same shape)."""
    picks = np.floor(np.arange(count) * len(polygon) / count).astype(np.int64)
    result: NDArray[np.float64] = polygon[picks]
    return result


def _convex_hull(points: NDArray[np.float64]) -> NDArray[np.float64]:
    """Monotone-chain convex hull of 2-D points (counter-clockwise)."""
    ordered = sorted({(float(x), float(y)) for x, y in points})

    def cross(
        o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
    ) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:  # noqa: PLR2004
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:  # noqa: PLR2004
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


# --------------------------------------------------------------------------- drawing
def _screen_bounds(parts: Sequence[PlacedPart], camera: Camera) -> Extent:
    cells = np.concatenate([np.asarray(p.cells, dtype=np.float64) for p in parts])
    lo, hi = cells.min(axis=0), cells.max(axis=0) + 1
    hi = hi + np.array([0.0, 0.0, STUD_HEIGHT / STUDS_PER_PLATE])
    box = np.array(
        [
            [x, y, z]
            for x in (lo[0], hi[0])
            for y in (lo[1], hi[1])
            for z in (lo[2], hi[2])
        ]
    )
    screen = camera.project(box * _SCALE)
    (x0, y0), (x1, y1) = screen.min(axis=0), screen.max(axis=0)
    return (float(x0), float(x1), float(y0), float(y1))


def _axes_aspect(options: PreviewOptions) -> float:
    """Width / height of the drawing area in :func:`draw_png`."""
    width, height = _axes_box(options)[2:]
    return (width * options.width_px) / (height * options.height_px)


def _axes_box(options: PreviewOptions) -> tuple[float, float, float, float]:
    m = options.margin
    top = 0.08 if options.title else m
    return (m, m, 1 - 2 * m, 1 - m - top)


def _fit_aspect(extent: Extent, aspect: float) -> Extent:
    """Widen or heighten ``extent`` (about its centre) to ``aspect``."""
    x0, x1, y0, y1 = extent
    width, height = x1 - x0, y1 - y0
    if width / height < aspect:
        grow = (height * aspect - width) / 2
        return (x0 - grow, x1 + grow, y0, y1)
    grow = (width / aspect - height) / 2
    return (x0, x1, y0 - grow, y1 + grow)


def _grown_frame(
    bounds: Extent, *, previous: Extent | None, final: Extent, aspect: float
) -> Extent:
    """Frame for a growing model: fits ``bounds``, never shrinks, has a floor.

    The frame keeps the final frame's bottom edge (the table) so the model
    does not jump up and down, and stays inside the final frame.
    """
    fx0, fx1, fy0, fy1 = final
    x0, x1, y0, y1 = bounds
    if previous is not None:
        x0, x1 = min(x0, previous[0]), max(x1, previous[1])
        y0, y1 = min(y0, previous[2]), max(y1, previous[3])
    floor = MIN_FRAME_SHARE * (fy1 - fy0)
    y0 = fy0
    y1 = min(max(y1, y0 + floor), fy1)
    height = y1 - y0
    width = max(x1 - x0, height * aspect)
    width = min(width, fx1 - fx0)
    height = max(height, width / aspect)
    y1 = y0 + height
    centre = (x0 + x1) / 2
    left = min(max(centre - width / 2, fx0), fx1 - width)
    return (left, left + width, y0, y1)


def _fit_extent(bounds: Extent) -> Extent:
    x0, x1, y0, y1 = bounds
    pad = 0.04 * max(x1 - x0, y1 - y0, 1e-6)
    return (x0 - pad, x1 + pad, y0 - pad, y1 + pad)


def fitted_extent(bounds: Extent, options: PreviewOptions) -> Extent:
    """Screen rectangle showing ``bounds`` with a margin, in the axes' aspect."""
    return _fit_aspect(_fit_extent(bounds), _axes_aspect(options))


def axes_pixels(options: PreviewOptions) -> tuple[int, int]:
    """Width and height in pixels of the drawing area of a preview."""
    _, _, width, height = _axes_box(options)
    return round(width * options.width_px), round(height * options.height_px)


def draw_image_png(
    image: NDArray[np.uint8], extent: Extent, options: PreviewOptions
) -> bytes:
    """Place an RGBA raster covering ``extent`` in a preview-styled PNG.

    Same layout, title and background as :func:`draw_png`; the raster may be
    larger than the drawing area (it is downsampled with antialiasing).
    """
    fig = Figure(
        figsize=(options.width_px / _DPI, options.height_px / _DPI),
        dpi=_DPI,
        facecolor=options.background,
    )
    FigureCanvasAgg(fig)
    ax = fig.add_axes(_axes_box(options))
    ax.imshow(
        image,
        extent=extent,
        origin="upper",
        interpolation="antialiased",
        interpolation_stage="rgba",
    )
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal")
    ax.set_axis_off()
    if options.title:
        fig.suptitle(options.title, fontsize=14)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=options.background)
    return buffer.getvalue()


def draw_png(
    polygons: Sequence[NDArray[np.float64]],
    fills: NDArray[np.float64] | list[object],
    options: PreviewOptions,
    extent: Extent | None,
) -> bytes:
    """Draw screen-space polygons (back to front) into a PNG.

    ``extent`` is the visible screen rectangle; ``None`` fits the polygons.
    """
    fig = Figure(
        figsize=(options.width_px / _DPI, options.height_px / _DPI),
        dpi=_DPI,
        facecolor=options.background,
    )
    FigureCanvasAgg(fig)
    ax = fig.add_axes(_axes_box(options))
    if len(polygons):
        ax.add_collection(
            PolyCollection(
                polygons,
                facecolors=fills,
                edgecolors=fills,
                linewidths=0.6,
                antialiased=True,
            )
        )
    if extent is None:
        if len(polygons):
            every = np.concatenate(list(polygons))
            (x0, y0), (x1, y1) = every.min(axis=0), every.max(axis=0)
            extent = _fit_extent((float(x0), float(x1), float(y0), float(y1)))
        else:
            extent = (0.0, 1.0, 0.0, 1.0)
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal")
    ax.set_axis_off()
    if options.title:
        fig.suptitle(options.title, fontsize=14)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=options.background)
    return buffer.getvalue()
