# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The whole conversion: 3D model -> LDraw, parts lists, PDF instructions.

This is the application layer behind ``mesh2brick convert``: it wires the
stages together and does the file I/O; every stage stays usable on its own.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import platformdirs

from mesh2brick.backends.legolization import (
    LegolizationBackend,
    color_info,
    color_quantizer,
    load_voxel_file,
    placeable_parts,
    whitelist,
)
from mesh2brick.backends.pyldraw import library_release, part_geometry
from mesh2brick.catalog.parts import PartSpec, part_specs, spec_cache_path
from mesh2brick.catalog.rebrickable import catalogue_colors, common_colors
from mesh2brick.catalog.whitelist import WhitelistError
from mesh2brick.export.bom import (
    BOM_FORMATS,
    Bom,
    bom_warnings,
    build_bom,
    write_boms,
)
from mesh2brick.ingest import load_model, supported_suffixes
from mesh2brick.render.pdf import PdfOptions, write_instructions
from mesh2brick.render.preview import PreviewOptions, render_preview
from mesh2brick.voxel.color import colors_needed
from mesh2brick.voxel.io import load_npz, save_npz
from mesh2brick.voxel.voxelize import voxelize

if TYPE_CHECKING:
    from collections.abc import Callable

    from mesh2brick.backends.protocols import StabilityReport
    from mesh2brick.config import Settings
    from mesh2brick.model import BrickModel
    from mesh2brick.voxel.color import ColorQuantizer
    from mesh2brick.voxel.grid import VoxelGrid

VOXEL_SUFFIXES = (".npz", ".vox", ".npy")


@dataclass(frozen=True, slots=True)
class ConvertResult:
    """Everything ``convert`` produced."""

    model: BrickModel
    stability: StabilityReport
    bom: Bom
    files: tuple[Path, ...]
    warnings: tuple[str, ...] = ()
    seconds: dict[str, float] = field(default_factory=dict)
    """Wall-clock seconds per stage."""


def convert(
    source: Path,
    settings: Settings,
    *,
    name: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> ConvertResult:
    """Run the full pipeline on ``source`` and write all requested outputs.

    Raises:
        mesh2brick.ingest.IngestError: for unreadable input.
        mesh2brick.backends.BackendError: if placement or export fails.
        ValueError: for unsupported input or configuration.
    """
    say = progress or (lambda _message: None)
    started = time.monotonic()
    deadline = started + settings.placement.time_limit_s
    clock = _Clock()
    warnings: list[str] = []
    stem = name or source.stem
    out_dir = settings.output.dir
    formats = settings.output.formats
    color_info(colors_needed(settings.color))  # fail fast on unknown colours

    with clock("voxelize"):
        grid = _grid(source, settings, warnings, say)
    files: list[Path] = [save_npz(grid, out_dir / f"{stem}.grid.npz")]
    say(f"voxels: {grid.filled_count:,} cells, grid {grid.shape} ({clock.last:.1f} s)")

    backend = LegolizationBackend(progress=say)
    with clock("place"):
        placement = backend.place(grid, settings, name=stem, deadline=deadline)
    model = placement.model
    warnings.extend(placement.notes)
    say(
        f"placed {model.part_count:,} parts in {model.step_count} steps "
        f"({clock.last:.1f} s)"
    )

    with clock("export"):
        suffix = ".mpd" if "mpd" in formats else ".ldr"
        ldraw_path = backend.write_ldraw(placement, out_dir / f"{stem}{suffix}")
        files.append(ldraw_path)
        checked = backend.verify_ldraw(ldraw_path)
        if checked != model.part_count:
            warnings.append(
                f"{ldraw_path.name}: re-read {checked} parts, "
                f"expected {model.part_count}"
            )
        files.append(model.save(out_dir / f"{stem}.bricks.json"))
        bom = build_bom(model)
        files.extend(write_boms(bom, out_dir, stem, formats))
        warnings.extend(bom_warnings(bom, formats))

    if "pdf" in formats:
        with clock("instructions"):
            report = write_instructions(
                model, bom, out_dir / f"{stem}.pdf", pdf_options(settings, stem)
            )
            files.append(report.path)
        say(
            f"instructions: {report.pages} pages, {model.step_count} steps "
            f"({clock.last:.1f} s)"
        )

    with clock("preview"):
        files.append(
            render_preview(model, out_dir / f"{stem}.png", PreviewOptions(title=stem))
        )
    elapsed = time.monotonic() - started
    if elapsed > settings.placement.time_limit_s:
        warnings.append(
            f"took {elapsed:.0f} s, more than placement.time_limit_s="
            f"{settings.placement.time_limit_s:.0f} s (the placement itself could "
            "not be cut shorter)"
        )
    return ConvertResult(
        model=model,
        stability=placement.stability,
        bom=bom,
        files=tuple(files),
        warnings=tuple(warnings),
        seconds=dict(clock.seconds),
    )


def pdf_options(settings: Settings, stem: str) -> PdfOptions:
    """Booklet layout from ``settings.output`` (``stem`` names the parts lists)."""
    output = settings.output
    files = {
        catalogue: f"{stem}{BOM_FORMATS[key]}"
        for catalogue, key in (
            ("bricklink", "bom_bricklink"),
            ("rebrickable", "bom_rebrickable"),
        )
        if key in output.formats
    }
    return PdfOptions(
        language=output.language,
        page_size=output.page_size,
        steps_per_page=output.steps_per_page,
        files=files,
    )


def _grid(
    source: Path,
    settings: Settings,
    warnings: list[str],
    say: Callable[[str], None],
) -> VoxelGrid:
    suffix = source.suffix.lower()
    if suffix == ".npz":
        return load_npz(source)
    if suffix in VOXEL_SUFFIXES:
        return load_voxel_file(source, height_unit=settings.voxel.height_unit)
    if suffix not in supported_suffixes():
        supported = ", ".join((*supported_suffixes(), *VOXEL_SUFFIXES))
        msg = f"unsupported input format {suffix!r}; supported: {supported}"
        raise ValueError(msg)
    model = load_model(source, settings.input)
    result = voxelize(model, settings, quantize=palette_for(settings))
    for note in (*model.warnings, *result.warnings):
        say(f"note: {note}")
    warnings.extend(result.warnings)
    if result.grid.filled_count == 0:
        msg = "voxelization produced no cells; increase input.target_studs"
        raise ValueError(msg)
    return result.grid


@dataclass(frozen=True, slots=True)
class CatalogOverview:
    """What ``mesh2brick catalog`` shows: placeable parts and their specs."""

    placeable: tuple[str, ...]
    specs: dict[str, PartSpec]
    allowed: frozenset[str] | None
    """Parts the current ``parts.*`` settings allow (``None`` if they are invalid)."""
    problem: str | None = None


def cache_dir() -> Path:
    """mesh2brick's cache directory (``MESH2BRICK_CACHE_DIR`` overrides it)."""
    override = os.environ.get("MESH2BRICK_CACHE_DIR")
    return (
        Path(override) if override else Path(platformdirs.user_cache_dir("mesh2brick"))
    )


def catalog_overview(settings: Settings) -> CatalogOverview:
    """Placeable parts with geometry-derived specs (cached) and the whitelist.

    Raises:
        mesh2brick.backends.BackendError: if the LDraw library is missing.
    """
    release = library_release()
    placeable = tuple(p.part for p in placeable_parts())
    specs = part_specs(
        placeable,
        part_geometry,
        cache=spec_cache_path(cache_dir(), release),
        release=release,
    )
    try:
        allowed: frozenset[str] | None = whitelist(settings).parts
        problem = None
    except WhitelistError as error:
        allowed, problem = None, str(error)
    return CatalogOverview(
        placeable=placeable, specs=specs, allowed=allowed, problem=problem
    )


def part_spec(part: str) -> PartSpec:
    """Spec of any LDraw part, derived from its geometry (cached).

    Raises:
        mesh2brick.backends.BackendError: for unknown parts.
    """
    release = library_release()
    return part_specs(
        [part],
        part_geometry,
        cache=spec_cache_path(cache_dir(), release),
        release=release,
    )[part]


def palette_for(settings: Settings) -> ColorQuantizer:
    """Matcher for model colours per ``color.palette`` (ADR 0008).

    ``common``: today's widely produced colours, ``solid``: every colour with
    BrickLink and Rebrickable numbers, ``all``: every solid LDraw colour.
    """
    match settings.color.palette:
        case "common":
            return color_quantizer(common_colors())
        case "solid":
            return color_quantizer(catalogue_colors())
        case _:
            return color_quantizer()


class _Clock:
    """Named wall-clock stopwatch used as a context manager."""

    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}
        self.last = 0.0
        self._name = ""
        self._start = 0.0

    def __call__(self, name: str) -> _Clock:
        self._name = name
        return self

    def __enter__(self) -> None:
        self._start = time.perf_counter()

    def __exit__(self, *exc_info: object) -> None:
        self.last = time.perf_counter() - self._start
        self.seconds[self._name] = round(self.last, 2)
