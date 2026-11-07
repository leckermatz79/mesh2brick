# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The whole conversion: 3D model -> LDraw, parts lists, PDF instructions.

This is the application layer behind ``mesh2brick convert``: it wires the
stages together and does the file I/O; every stage stays usable on its own.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final

import platformdirs

from mesh2brick.backends.legolization import (
    LegolizationBackend,
    color_info,
    color_quantizer,
    export_reserve_s,
    load_voxel_file,
    placeable_parts,
    placement_footprint,
    replacement_options,
    whitelist,
)
from mesh2brick.backends.protocols import BackendError
from mesh2brick.backends.pyldraw import library_release, part_geometry
from mesh2brick.catalog.parts import PartSpec, part_specs, spec_cache_path
from mesh2brick.catalog.rebrickable import (
    catalogue_colors,
    color_name,
    common_colors,
    part_name,
)
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
from mesh2brick.render.preview import PreviewOptions, render_png, render_preview
from mesh2brick.render.text import colour_label, sized_label
from mesh2brick.voxel.color import colors_needed
from mesh2brick.voxel.io import load_npz, save_npz
from mesh2brick.voxel.voxelize import voxelize

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from mesh2brick.agent.client import Sender
    from mesh2brick.agent.feedback import FeedbackStore
    from mesh2brick.agent.session import LlmReport
    from mesh2brick.agent.tasks import PartQuestion
    from mesh2brick.backends.legolization import Piece
    from mesh2brick.backends.protocols import Placement, StabilityReport
    from mesh2brick.config import Settings
    from mesh2brick.model import BrickModel
    from mesh2brick.render.text import Language
    from mesh2brick.voxel.color import ColorQuantizer
    from mesh2brick.voxel.grid import VoxelGrid

VOXEL_SUFFIXES = (".npz", ".vox", ".npy")
LLM_MIN_S: Final = 30.0
"""The LLM layer is skipped when less time is left before the export."""


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
    llm: LlmReport | None = None
    """What the LLM layer did and cost (``None``: not used)."""


def convert(
    source: Path,
    settings: Settings,
    *,
    name: str | None = None,
    progress: Callable[[str], None] | None = None,
    send: Sender | None = None,
) -> ConvertResult:
    """Run the full pipeline on ``source`` and write all requested outputs.

    With ``llm.enabled`` the LLM layer improves the steps before export
    (``send`` replaces the Anthropic API, for tests).

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

    outcome = LlmOutcome(placement, None)
    if settings.llm.enabled:
        with clock("llm"):
            outcome = _llm_in_time(
                placement,
                backend,
                settings,
                source=source,
                left=deadline - time.monotonic(),
                say=say,
                send=send,
            )
        files.extend(_llm_files(outcome, out_dir / f"{stem}.llm.json", say))
        warnings.extend(outcome.notes)
    placement, llm = outcome.placement, outcome.report
    model = placement.model

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
                model,
                bom,
                out_dir / f"{stem}.pdf",
                replace(pdf_options(settings, stem), replacements=outcome.replacements),
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
            f"took {elapsed:.0f} s, {elapsed - settings.placement.time_limit_s:.0f} s "
            f"more than placement.time_limit_s={settings.placement.time_limit_s:.0f} s "
            "(the time kept free for the export was too short)"
        )
    return ConvertResult(
        model=model,
        stability=placement.stability,
        bom=bom,
        files=tuple(files),
        warnings=tuple(warnings),
        seconds=dict(clock.seconds),
        llm=llm,
    )


def _llm_in_time(
    placement: Placement,
    backend: LegolizationBackend,
    settings: Settings,
    *,
    source: Path,
    left: float,
    say: Callable[[str], None],
    send: Sender | None,
) -> LlmOutcome:
    """:func:`improve_with_llm`, unless the time limit leaves too little time.

    ``left`` is the time until ``placement.time_limit_s``; the export's
    share is kept free.
    """
    left -= export_reserve_s(placement.model.part_count)
    if left < LLM_MIN_S:
        note = (
            f"LLM layer skipped: only {max(left, 0):.0f} s of placement.time_limit_s "
            "left before the export"
        )
        return LlmOutcome(placement, None, (note,))
    return improve_with_llm(
        placement, backend, settings, source=source, say=say, send=send
    )


@dataclass(frozen=True, slots=True)
class LlmOutcome:
    """What :func:`improve_with_llm` produced.

    Attributes:
        placement: the placement with merged steps, sections and texts.
        report: tasks, tokens and cost (``None``: the layer could not start).
        notes: things the user should know.
        replacements: chosen replacement per ``(part, colour)`` LEGO does not
            make, worded in the booklet language (``choose_part``).
    """

    placement: Placement
    report: LlmReport | None
    notes: tuple[str, ...] = ()
    replacements: dict[tuple[str, int], str] = field(default_factory=dict)


def improve_with_llm(
    placement: Placement,
    backend: LegolizationBackend,
    settings: Settings,
    *,
    source: Path,
    say: Callable[[str], None],
    send: Sender | None = None,
    store: FeedbackStore | None = None,
) -> LlmOutcome:
    """Run the LLM layer on a placement (SPEC Phase 7, ADR 0013).

    Claude may merge steps (applied by the backend, so the LDraw file follows),
    name build sections, write step texts and choose replacement parts;
    everything is checked first. ``send`` replaces the Anthropic API (tests),
    ``store`` the feedback store in the user's data folder.

    Raises:
        mesh2brick.backends.BackendError: if the backend cannot merge steps.
    """
    from mesh2brick.agent.client import LlmError, anthropic_sender  # noqa: PLC0415
    from mesh2brick.agent.feedback import (  # noqa: PLC0415
        FeedbackStore,
        default_store_path,
    )
    from mesh2brick.agent.session import LlmSession  # noqa: PLC0415

    llm = settings.llm
    try:
        send = send or anthropic_sender()
    except LlmError as error:
        return LlmOutcome(placement, None, (f"LLM layer skipped: {error}",))
    if store is None and llm.feedback:
        store = FeedbackStore(default_store_path())
    language = settings.output.language
    session = LlmSession(
        settings,
        placement.model,
        send=send,
        render=step_picture,
        picture=model_picture,
        source=str(source),
        examples=(
            (lambda task: store.examples(task, language, llm.examples))
            if store is not None
            else None
        ),
        notes=store.notes(3) if store is not None else (),
    )
    say(f"LLM: structuring the steps ({llm.model})")
    grouping = session.group_steps()
    if grouping.merges:
        placement = backend.merge_steps(placement, grouping.merges)
        session.use(placement.model)
    if session.wants("write_step_text"):
        say(f"LLM: writing step texts for {placement.model.step_count} steps")
    session.write_step_texts()
    model = session.annotate(placement.model)
    replacements: dict[tuple[str, int], str] = {}
    if session.wants("choose_part") and settings.parts.availability == "report":
        questions, options = part_questions(model)
        chosen = session.choose_parts(questions)
        replacements = {
            (questions[i].part, questions[i].color): replacement_text(
                options[i][o], model, language
            )
            for i, o in chosen.items()
        }
    report = session.finish(model, store)
    notes = list(session.notes_for_user)
    notes.extend(
        f"LLM {task.task} not used: {task.detail}"
        for task in report.tasks
        if task.status in ("fallback", "skipped")
    )
    return LlmOutcome(
        replace(placement, model=model), report, tuple(notes), replacements
    )


def part_questions(
    model: BrickModel,
) -> tuple[list[PartQuestion], list[tuple[tuple[Piece, ...], ...]]]:
    """Parts LEGO does not make in their colour, with catalogue-checked options."""
    from mesh2brick.agent.tasks import PartQuestion  # noqa: PLC0415

    questions: list[PartQuestion] = []
    options: list[tuple[tuple[Piece, ...], ...]] = []
    for line in build_bom(model).not_produced():
        try:
            found = replacement_options(line.part, line.color, common_colors())
        except BackendError:
            continue
        if not found:
            continue
        name = replacement_text(((line.part, line.color),), model, "en")
        questions.append(
            PartQuestion(
                part=line.part,
                color=line.color,
                label=f"{line.quantity}x {name.removeprefix('1x ')}",
                options=tuple(
                    replacement_text(option, model, "en")
                    + (" (same colour)" if option[0][1] == line.color else "")
                    for option in found
                ),
            )
        )
        options.append(found)
    return questions, options


def replacement_text(
    pieces: Sequence[Piece], model: BrickModel, language: Language
) -> str:
    """``2x Brick 1 x 4 Coral`` for the parts of a replacement."""
    counts = Counter(pieces)
    words = []
    for (part, colour), count in counts.items():
        size = placement_footprint(part)
        category = next(p.category for p in placeable_parts() if p.part == part)
        label = sized_label(part, category, size, language, part_name(part))
        info = model.colors.get(colour)
        colour_name = info.name if info is not None else color_name(colour)
        words.append(f"{count}x {label} {colour_label(colour, colour_name, language)}")
    return ", ".join(words)


LLM_STEP_PX: Final = (560, 420)
"""Pictures for ``render_preview``: about 300 input tokens each."""
LLM_MODEL_PX: Final = (800, 600)


def step_picture(model: BrickModel, step: int) -> bytes:
    """The model after a 0-based step, as the LLM layer's preview tool shows it."""
    width, height = LLM_STEP_PX
    options = PreviewOptions(width_px=width, height_px=height, up_to_step=step)
    return render_png(model, options)


def model_picture(model: BrickModel) -> bytes:
    """The finished model for the LLM layer's first message."""
    width, height = LLM_MODEL_PX
    return render_png(model, PreviewOptions(width_px=width, height_px=height))


def _llm_files(
    outcome: LlmOutcome, path: Path, say: Callable[[str], None]
) -> list[Path]:
    report = outcome.report
    if report is None:
        return []
    say(f"LLM ({report.model}): {report.summary()}")
    return [write_llm_report(report, path)]


def write_llm_report(report: LlmReport, path: Path) -> Path:
    """Write the LLM report (tasks, tokens, cost, accepted outputs) as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report.as_dict(), indent=1, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


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
        msg = "voxelization produced no cells; make the model bigger (e.g. --size 30cm)"
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
