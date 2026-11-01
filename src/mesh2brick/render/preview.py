# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Quick PNG previews of a :class:`~mesh2brick.model.BrickModel`.

A tiny orthographic painter's-algorithm renderer on top of matplotlib's 2-D
``PolyCollection``: every occupied grid cell (1 x 1 stud x 1 plate) is drawn
back to front, only faces that are exposed and facing the camera, with dark
strips along part boundaries and studs on exposed tops. Because all cells are
translates of one box on a lattice, back-to-front ordering by cell depth is
exact - unlike matplotlib's own 3-D mode, which mis-sorts large faces.

It is meant for self-checks, STATUS reports and as fallback instruction images
when no LDraw renderer (LeoCAD/LDView) is installed. Slopes are drawn as their
bounding cells for now.

Only matplotlib's object-oriented API is used (no ``pyplot``), so rendering
never touches global GUI state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import PolyCollection
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure

from mesh2brick.voxel.grid import LDU_PER_PLATE, LDU_PER_STUD

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from mesh2brick.model import BrickModel, Cell

STUDS_PER_PLATE: Final = LDU_PER_PLATE / LDU_PER_STUD  # cell height: 0.4 studs
STUD_RADIUS: Final = 0.3  # 4.8 mm stud diameter / 8 mm pitch
STUD_HEIGHT: Final = 0.21  # 1.7 mm / 8 mm
_EDGE_WIDTH: Final = 0.035  # boundary strip width in studs
_STUD_SEGMENTS: Final = 20
_FALLBACK_RGB: Final = "#9ba19d"
_GHOST_MIX: Final = 0.72
_FACING_EPS: Final = 1e-9
_DPI: Final = 100
_NO_STUD_CATEGORIES: Final = frozenset({"tile", "slope"})

# Face normals and a fake directional light (brightness per face direction).
_DIRECTIONS: Final[tuple[tuple[Cell, float], ...]] = (
    ((0, 0, 1), 1.0),
    ((0, 0, -1), 0.45),
    ((1, 0, 0), 0.66),
    ((-1, 0, 0), 0.82),
    ((0, 1, 0), 0.9),
    ((0, -1, 0), 0.74),
)

Color = tuple[float, float, float]


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
    up_to_step: int | None = None
    """Draw only steps ``<= up_to_step`` (0-based): that step in full colour,
    earlier ones faded. ``None`` draws the finished model."""
    background: str = "#ffffff"


@dataclass(frozen=True, slots=True)
class _Camera:
    right: NDArray[np.float64]
    up: NDArray[np.float64]
    toward_viewer: NDArray[np.float64]

    @classmethod
    def from_angles(cls, elevation: float, azimuth: float) -> _Camera:
        elev, azim = math.radians(elevation), math.radians(azimuth)
        toward = np.array(
            [
                math.cos(elev) * math.cos(azim),
                math.cos(elev) * math.sin(azim),
                math.sin(elev),
            ]
        )
        right = np.array([-math.sin(azim), math.cos(azim), 0.0])
        up = np.cross(toward, right)
        return cls(right=right, up=up, toward_viewer=toward)

    def project(self, points: NDArray[np.float64]) -> NDArray[np.float64]:
        """World points ``(n, 3)`` (studs, z in studs) -> screen ``(n, 2)``."""
        return np.stack([points @ self.right, points @ self.up], axis=-1)


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
    parts = [
        p
        for p in model.parts
        if options.up_to_step is None or p.step <= options.up_to_step
    ]
    if not parts:
        msg = "nothing to render: the model (or step selection) has no parts"
        raise ValueError(msg)

    camera = _Camera.from_angles(options.elevation, options.azimuth)
    background = to_rgb(options.background)
    owner: dict[Cell, int] = {}
    colour: dict[int, Color] = {}
    studded: dict[int, bool] = {}
    for index, part in enumerate(parts):
        base = to_rgb(_rgb_hex(model, part.color))
        if options.up_to_step is not None and part.step < options.up_to_step:
            base = _mix(base, background, _GHOST_MIX)
        colour[index] = base
        studded[index] = part.category not in _NO_STUD_CATEGORIES
        for cell in part.cells:
            owner[cell] = index

    polygons, fills = _draw_cells(owner, colour, studded, camera)

    fig = Figure(
        figsize=(options.width_px / _DPI, options.height_px / _DPI),
        dpi=_DPI,
        facecolor=options.background,
    )
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.02, 0.02, 0.96, 0.9 if options.title else 0.96))
    ax.add_collection(
        PolyCollection(
            polygons,
            facecolors=fills,
            edgecolors=fills,
            linewidths=0.6,
            antialiased=True,
        )
    )
    every = np.concatenate(polygons)
    (xmin, ymin), (xmax, ymax) = every.min(axis=0), every.max(axis=0)
    pad = 0.04 * max(xmax - xmin, ymax - ymin)
    ax.set_xlim(xmin - pad, xmax + pad)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.set_aspect("equal")
    ax.set_axis_off()
    if options.title:
        fig.suptitle(options.title, fontsize=14)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=options.background)
    return path


def _draw_cells(
    owner: dict[Cell, int],
    colour: dict[int, Color],
    studded: dict[int, bool],
    camera: _Camera,
) -> tuple[list[NDArray[np.float64]], list[Color]]:
    """Polygons (screen space) and fill colours in back-to-front order."""
    view = camera.toward_viewer
    scale = np.array([1.0, 1.0, STUDS_PER_PLATE])
    visible_dirs = [
        (np.array(d), shade)
        for d, shade in _DIRECTIONS
        if np.dot(d, view) > _FACING_EPS
    ]
    cells = sorted(owner, key=lambda c: float(np.dot(np.array(c) * scale, view)))
    polygons: list[NDArray[np.float64]] = []
    fills: list[Color] = []
    for cell in cells:
        part = owner[cell]
        base = colour[part]
        edge = (base[0] * 0.35, base[1] * 0.35, base[2] * 0.35)
        origin = np.array(cell, dtype=np.float64)
        for normal, shade in visible_dirs:
            neighbour = _offset(cell, normal)
            if neighbour in owner:
                continue
            corners = _face_corners(origin, normal) * scale
            polygons.append(camera.project(corners))
            fills.append(_shaded(base, shade))
            for strip in _boundary_strips(cell, normal, corners, owner):
                polygons.append(camera.project(strip))
                fills.append(edge)
        top = _offset(cell, np.array([0, 0, 1]))
        is_top_of_part = owner.get(top) != part
        if studded[part] and is_top_of_part and top not in owner:
            centre = (origin + np.array([0.5, 0.5, 1.0])) * scale
            for polygon, shade in _stud(centre, camera):
                polygons.append(polygon)
                fills.append(_shaded(base, shade))
    return polygons, fills


def _offset(cell: Cell, direction: NDArray[np.int_]) -> Cell:
    return (
        cell[0] + int(direction[0]),
        cell[1] + int(direction[1]),
        cell[2] + int(direction[2]),
    )


def _face_corners(
    origin: NDArray[np.float64], normal: NDArray[np.int_]
) -> NDArray[np.float64]:
    """The four corners (unit-cell space) of the face of a cell along ``normal``."""
    axis = int(np.flatnonzero(normal)[0])
    u_axis, v_axis = [a for a in range(3) if a != axis]
    base = origin.copy()
    if normal[axis] > 0:
        base[axis] += 1.0
    corners = np.repeat(base[None, :], 4, axis=0)
    corners[1, u_axis] += 1.0
    corners[2, u_axis] += 1.0
    corners[2, v_axis] += 1.0
    corners[3, v_axis] += 1.0
    return corners


def _boundary_strips(
    cell: Cell,
    normal: NDArray[np.int_],
    corners: NDArray[np.float64],
    owner: dict[Cell, int],
) -> list[NDArray[np.float64]]:
    """Thin dark strips along face edges that are part boundaries or creases."""
    axis = int(np.flatnonzero(normal)[0])
    part = owner[cell]
    strips: list[NDArray[np.float64]] = []
    # Edges in corner order: (0,1) along u at v=0, (1,2) along v at u=1, ...
    edges = ((0, 1), (1, 2), (2, 3), (3, 0))
    u_axis, v_axis = [a for a in range(3) if a != axis]
    steps = (
        (v_axis, -1),
        (u_axis, +1),
        (v_axis, +1),
        (u_axis, -1),
    )
    for (a, b), (step_axis, sign) in zip(edges, steps, strict=True):
        delta = np.zeros(3, dtype=np.int_)
        delta[step_axis] = sign
        beside = _offset(cell, delta)
        continues = owner.get(beside) == part and _offset(beside, normal) not in owner
        if continues:
            continue
        # A rectangle reaching perpendicularly into the face, so strips of
        # neighbouring cells join into one continuous line.
        inward = -delta.astype(np.float64) * _EDGE_WIDTH
        p, q = corners[a], corners[b]
        strips.append(np.array([p, q, q + inward, p + inward]))
    return strips


def _stud(
    centre: NDArray[np.float64], camera: _Camera
) -> list[tuple[NDArray[np.float64], float]]:
    """Polygons for one stud on a top face: shaded side band, then the cap."""
    angles = np.linspace(0.0, 2 * math.pi, _STUD_SEGMENTS, endpoint=False)
    ring = np.stack(
        [
            np.cos(angles) * STUD_RADIUS,
            np.sin(angles) * STUD_RADIUS,
            np.zeros_like(angles),
        ],
        axis=-1,
    )
    bottom = camera.project(centre + ring)
    top = camera.project(centre + ring + np.array([0.0, 0.0, STUD_HEIGHT]))
    # Side band = convex hull of both projected rings (a cylinder's silhouette).
    side = _convex_hull(np.concatenate([bottom, top]))
    return [(side, 0.62), (top, 1.08)]


def _convex_hull(points: NDArray[np.float64]) -> NDArray[np.float64]:
    """Monotone-chain convex hull of 2-D points (counter-clockwise)."""
    ordered = sorted({(float(x), float(y)) for x, y in points})
    if len(ordered) < 3:  # noqa: PLR2004 - a hull needs three points
        return np.array(ordered)

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


def _rgb_hex(model: BrickModel, code: int) -> str:
    info = model.colors.get(code)
    return info.rgb_hex if info is not None else _FALLBACK_RGB


def _shaded(base: Color, shade: float) -> Color:
    return (
        min(1.0, base[0] * shade),
        min(1.0, base[1] * shade),
        min(1.0, base[2] * shade),
    )


def _mix(a: Color, b: Color, t: float) -> Color:
    return (
        a[0] * (1 - t) + b[0] * t,
        a[1] * (1 - t) + b[1] * t,
        a[2] * (1 - t) + b[2] * t,
    )
