# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""``mesh2brick inspect``: what an input file will give, before converting.

Reads the file, voxelizes it with the current settings and reports what a
builder wants to know up front: size in the file and in LEGO, which colour
information the file has and which LEGO colours it becomes, warnings, and a
rough part count. No placement runs, so this takes seconds even for big
models. The picture puts the model as read next to its voxels, seen from the
same side.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import numpy as np

from mesh2brick.backends.legolization import load_voxel_file
from mesh2brick.ingest import load_model, supported_suffixes
from mesh2brick.pipeline import VOXEL_SUFFIXES, palette_for
from mesh2brick.render.mesh import NEUTRAL_RGB, render_mesh_png, side_by_side
from mesh2brick.render.preview import PreviewOptions, grid_to_model, render_png
from mesh2brick.voxel.color import sample_rgb
from mesh2brick.voxel.io import load_npz
from mesh2brick.voxel.voxelize import hollow, voxelize

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from mesh2brick.config import Settings
    from mesh2brick.ingest import MeshModel
    from mesh2brick.ingest.base import ColorKind
    from mesh2brick.model import ColorInfo
    from mesh2brick.voxel.grid import VoxelGrid
    from mesh2brick.voxel.voxelize import VoxelizeReport

FOOTPRINTS: Final = ((2, 8), (2, 6), (2, 4), (2, 3), (2, 2), (1, 8), (1, 6), (1, 4))
"""Brick/plate footprints (studs) for the quick fill, beside 1 x 3, 1 x 2, 1 x 1."""
ESTIMATE_FACTORS: Final = (0.9, 1.3, 2.0)
"""Placed parts per part of the quick fill (low, typical, high). Measured on
15 conversions (docs/benchmarks.md, Phase 8): 14 between 0.93 and 1.76, median
1.3. The quick fill knows neither the hollowing nor the stability repairs,
which add parts; thin wide slabs that legolization builds from plates can
need more (3.6 x for a castle courtyard)."""
MAX_FILL_CELLS: Final = 400_000
"""Bigger grids are estimated from their cell count (the fill is a Python loop)."""
CELLS_PER_PART: Final = 6.0
"""Fallback: filled cells per part of the quick fill (typical for big models)."""
PANEL_PX: Final = 800


@dataclass(frozen=True, slots=True)
class Inspection:
    """Everything ``inspect`` found out about one input file."""

    name: str
    source: Path
    grid: VoxelGrid
    shell: VoxelGrid
    """The cells that will be built (``grid`` hollowed per ``voxel.fill``)."""
    model: MeshModel | None = None
    """The normalised mesh (``None`` for voxel files)."""
    report: VoxelizeReport | None = None
    surface_colors: dict[ColorKind, float] = field(default_factory=dict)
    """Share of the surface area each colour source covers."""
    warnings: tuple[str, ...] = ()
    seconds: float = 0.0

    @property
    def color_cells(self) -> list[tuple[int, int]]:
        """``(LDraw code, cells)`` of the shell, most frequent first."""
        codes, counts = np.unique(
            self.shell.color[self.shell.occupancy], return_counts=True
        )
        pairs = [(int(c), int(n)) for c, n in zip(codes, counts, strict=True)]
        return sorted(pairs, key=lambda pair: (-pair[1], pair[0]))

    @property
    def parts_estimate(self) -> tuple[int, int, int]:
        """Rough ``(low, expected, high)`` part count of the converted model.

        Based on :func:`quick_fill` of the solid grid; the real placement
        hollows the model and repairs stability, which the factors cover.
        """
        filled = self.grid.filled_count
        fill = (
            quick_fill(self.grid.occupancy)
            if filled <= MAX_FILL_CELLS
            else filled / CELLS_PER_PART
        )
        low, typical, high = (max(1, round(fill * f)) for f in ESTIMATE_FACTORS)
        return low, typical, high


def quick_fill(occupancy: NDArray[np.bool_]) -> int:
    """Parts a layer-by-layer greedy fill with the largest bricks needs.

    Every layer is scanned cell by cell; the first free cell gets the largest
    footprint (either orientation) that fits into free cells. A quick stand-in
    for placement, used only for the estimate.
    """
    shapes = sorted(
        {s for w, d in (*FOOTPRINTS, (1, 3), (1, 2), (1, 1)) for s in ((w, d), (d, w))},
        key=lambda s: (-s[0] * s[1], s),
    )
    nx, ny, nz = occupancy.shape
    parts = 0
    for z in range(nz):
        free = occupancy[:, :, z].copy()
        for x, y in np.argwhere(free):
            if not free[x, y]:
                continue
            for w, d in shapes:
                if x + w <= nx and y + d <= ny and free[x : x + w, y : y + d].all():
                    free[x : x + w, y : y + d] = False
                    parts += 1
                    break
    return parts


def inspect_file(source: Path, settings: Settings, *, name: str) -> Inspection:
    """Read and voxelize ``source`` with ``settings`` (no placement).

    Raises:
        mesh2brick.ingest.IngestError: for unreadable model files.
        mesh2brick.backends.BackendError: for unreadable voxel files.
        ValueError: for unsupported file types.
    """
    started = time.perf_counter()
    suffix = source.suffix.lower()
    if suffix in VOXEL_SUFFIXES:
        grid = (
            load_npz(source)
            if suffix == ".npz"
            else load_voxel_file(source, height_unit=settings.voxel.height_unit)
        )
        return Inspection(
            name=name,
            source=source,
            grid=grid,
            shell=_shell(grid, settings),
            seconds=time.perf_counter() - started,
        )
    if suffix not in supported_suffixes():
        supported = ", ".join((*supported_suffixes(), *VOXEL_SUFFIXES))
        msg = f"unsupported input format {suffix!r}; supported: {supported}"
        raise ValueError(msg)
    model = load_model(source, settings.input)
    result = voxelize(model, settings, quantize=palette_for(settings))
    return Inspection(
        name=name,
        source=source,
        grid=result.grid,
        shell=_shell(result.grid, settings),
        model=model,
        report=result.report,
        surface_colors=surface_shares(model),
        warnings=(*model.warnings, *result.warnings),
        seconds=time.perf_counter() - started,
    )


def _shell(grid: VoxelGrid, settings: Settings) -> VoxelGrid:
    if settings.voxel.fill != "hollow" or not grid.filled_count:
        return grid
    return hollow(grid, settings.voxel.wall_thickness)


def surface_shares(model: MeshModel) -> dict[ColorKind, float]:
    """Share of the surface area covered by each colour source of the file."""
    colors = model.colors
    if colors is None:
        return {}
    area = np.asarray(model.mesh.area_faces, dtype=np.float64)
    total = float(area.sum()) or 1.0
    return {kind: float(area[colors.mask(kind)].sum()) / total for kind in colors.kinds}


def face_rgb(model: MeshModel) -> NDArray[np.uint8] | None:
    """One sRGB colour per face (at its centre), ``None`` without colours."""
    colors = model.colors
    if colors is None or not colors.kinds:
        return None
    faces = np.arange(colors.face_count, dtype=np.int64)
    centre = np.full((len(faces), 3), 1.0 / 3.0)
    rgb, known = sample_rgb(colors, faces, centre, colors.kinds)
    rgb[~known] = NEUTRAL_RGB
    return rgb


def render_inspection(
    inspection: Inspection, colors: dict[int, ColorInfo], *, panel_px: int = PANEL_PX
) -> bytes:
    """PNG: the model as read (left, if it is a mesh) and its voxels (right)."""
    grid = inspection.grid
    nx, ny, nz = grid.shape
    unit = "bricks" if grid.height_unit == "brick" else "plates"
    panels: list[bytes] = []
    if inspection.model is not None:
        model = inspection.model
        panels.append(
            render_mesh_png(
                np.asarray(model.mesh.vertices),
                np.asarray(model.mesh.faces),
                face_rgb(model),
                PreviewOptions(
                    width_px=panel_px,
                    height_px=panel_px,
                    title=f"{inspection.source.name}: {len(model.mesh.faces):,} "
                    "triangles",
                ),
                two_sided=not model.watertight,
            )
        )
    panels.append(
        render_png(
            grid_to_model(grid, colors),
            PreviewOptions(
                width_px=panel_px,
                height_px=panel_px,
                title=f"voxels: {nx} x {ny} studs x {nz} {unit}",
            ),
        )
    )
    return side_by_side(panels)


def inspection_text(
    inspection: Inspection, settings: Settings, colors: dict[int, ColorInfo]
) -> str:
    """Human-readable result of ``inspect``."""
    grid, shell, model, report = (
        inspection.grid,
        inspection.shell,
        inspection.model,
        inspection.report,
    )
    nx, ny, nz = grid.shape
    unit = "bricks" if grid.height_unit == "brick" else "plates"
    cell_cm = 0.96 if grid.height_unit == "brick" else 0.32
    lines: list[str] = []
    if model is None:
        lines.append(
            f"{inspection.source.name}: voxel grid, {grid.filled_count:,} filled cells"
        )
    else:
        size = np.asarray(model.mesh.extents)
        lines += [
            f"{inspection.source.name}: {len(model.mesh.faces):,} triangles, "
            f"{model.part_count} part(s)"
            + (f" ({_names(model.part_names)})" if model.part_count > 1 else ""),
            f"  size in the file: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm, "
            + ("closed" if model.watertight else "NOT closed (holes)"),
            "  colours in the file: " + _color_sources(inspection.surface_colors),
        ]
    if report is not None:
        lines.append(
            f"  scale: {report.pitch_mm:.2f} mm of model per stud"
            + (
                f" (longest axis -> {settings.input.target_studs} studs)"
                if settings.input.scale_mode == "studs"
                else ""
            )
        )
    lines += [
        f"  grid: {nx} x {ny} studs x {nz} {unit}, {grid.filled_count:,} filled cells",
        f"  LEGO size: {nx * 0.8:.1f} x {ny * 0.8:.1f} x {nz * cell_cm:.1f} cm",
    ]
    if report is not None and report.volume_error is not None:
        lines.append(f"  volume vs. mesh: {report.volume_error * 100:+.1f} %")
    if shell is not grid:
        lines.append(
            f"  hollow shell (wall {settings.voxel.wall_thickness}): "
            f"{shell.filled_count:,} cells to build"
        )
    lines.append("  LEGO colours: " + _lego_colors(inspection.color_cells, colors))
    if shell.filled_count:
        low, expected, high = inspection.parts_estimate
        lines.append(
            f"  rough estimate: about {expected:,} parts ({low:,}-{high:,}); "
            "`convert` gives the exact count"
        )
    return "\n".join(lines)


def _names(names: tuple[str, ...], limit: int = 5) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f", ... ({len(names) - limit} more)" if len(names) > limit else "")


_SOURCE_LABELS: Final[dict[str, str]] = {
    "cad": "part/material colours",
    "vertex": "vertex colours",
    "texture": "textures",
}


def _color_sources(shares: dict[ColorKind, float]) -> str:
    if not shares:
        return "none (the model gets color.single_color)"
    return ", ".join(
        f"{_SOURCE_LABELS[kind]} on {share * 100:.0f} % of the surface"
        for kind, share in shares.items()
    )


def _lego_colors(
    cells: list[tuple[int, int]], colors: dict[int, ColorInfo], limit: int = 6
) -> str:
    if not cells:
        return "-"
    total = sum(n for _, n in cells)
    named = [
        f"{colors[code].name.replace('_', ' ') if code in colors else code} "
        f"{max(1, round(100 * n / total))} %"
        for code, n in cells[:limit]
    ]
    rest = len(cells) - limit
    return ", ".join(named) + (f", +{rest} more" if rest > 0 else "")
