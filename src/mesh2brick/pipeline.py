# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The whole conversion: 3D model -> LDraw, parts lists, PDF instructions.

This is the application layer behind ``mesh2brick convert``: it wires the
stages together and does the file I/O; every stage stays usable on its own.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mesh2brick.backends.legolization import (
    LegolizationBackend,
    color_info,
    load_voxel_file,
)
from mesh2brick.export.bom import Bom, bom_warnings, build_bom, write_boms
from mesh2brick.ingest import load_model, supported_suffixes
from mesh2brick.render.preview import PreviewOptions, render_preview, render_step_images
from mesh2brick.voxel.color import colors_needed
from mesh2brick.voxel.io import load_npz, save_npz
from mesh2brick.voxel.voxelize import voxelize

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mesh2brick.backends.protocols import StabilityReport
    from mesh2brick.config import Settings
    from mesh2brick.model import BrickModel
    from mesh2brick.voxel.grid import VoxelGrid

VOXEL_SUFFIXES = (".npz", ".vox", ".npy")
STEP_IMAGE_SIZE = (640, 480)


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
            width, height = STEP_IMAGE_SIZE
            images = render_step_images(
                model, PreviewOptions(width_px=width, height_px=height)
            )
            files.append(
                backend.write_instructions(
                    placement,
                    out_dir / f"{stem}.pdf",
                    images,
                    page_size=settings.output.page_size,
                )
            )
        say(f"instructions: {model.step_count} step images ({clock.last:.1f} s)")
    if settings.output.language != "en" and "pdf" in formats:
        warnings.append(
            f"output.language={settings.output.language}: the PDF text is still "
            "English (legolization booklet); translations follow in Phase 6"
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
    result = voxelize(model, settings)
    for note in (*model.warnings, *result.warnings):
        say(f"note: {note}")
    warnings.extend(result.warnings)
    if result.grid.filled_count == 0:
        msg = "voxelization produced no cells; increase input.target_studs"
        raise ValueError(msg)
    return result.grid


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
