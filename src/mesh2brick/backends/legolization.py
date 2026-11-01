# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Adapter to `legolization <https://github.com/hbmartin/legolization>`_.

This is the **only** module that translates between mesh2brick's z-up grid
world and legolization (which in turn owns the LDraw -Y-up transform):

* our :class:`~mesh2brick.voxel.grid.VoxelGrid` (cells of one brick or plate
  height) is resampled to legolization's plate-layer grid,
* our :class:`~mesh2brick.config.Settings` become a ``PipelineConfig``,
* legolization's ``Layout``/``InstructionPlan`` become a
  :class:`~mesh2brick.model.BrickModel`.

Backend-specific options (``placement.backend_options``) are passed through
to ``PipelineConfig`` after validation against its real field names.

Local patch (transitional, see docs/UPSTREAM.md #2): legolization 0.5.0 tries
three HiGHS variants for every stability LP (presolve on, presolve off,
interior point) but gives none of them a time limit. HiGHS presolve can stall
on some LPs (reproducer: the low-poly bunny at 16 studs, after the slope pass
and again during step sequencing), which hangs the whole pipeline. We add a
time limit to all but the last attempt - in both LP paths (scipy ``linprog``
and direct ``highspy``) - so a stalled variant gives up and the next one,
which solves such LPs in seconds, takes over.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import math
import multiprocessing
import time
import types
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final, Literal, cast

import highspy
import numpy as np
from legolization import MeshOptions, PipelineConfig, PipelineResult, run
from legolization import VoxelGrid as LegoGrid
from legolization.color import Palette, default_palette
from legolization.graph import ConnectionGraph
from legolization.instructions.bom import bill_of_materials
from legolization.instructions.booklet import BookletConfig, ModelStats, write_booklet
from legolization.instructions.chunking import chunk_bands, mirror_pairs
from legolization.instructions.render import StepImages
from legolization.instructions.sequencer import (
    BuildStep as LegoStep,
)
from legolization.instructions.sequencer import (
    InstructionPlan,
    InstructionsConfig,
    plan_instructions,
)
from legolization.ldraw_in import LdrawImportError, layout_from_ldraw
from legolization.ldraw_out import write_model
from legolization.mesh import grid_from_mesh
from legolization.placement.registry import strategy_names
from legolization.placement.repair import RepairConfig
from legolization.stability import solver as _lego_solver
from legolization.stability.solver import StabilityResult, analyze

from mesh2brick.backends.protocols import BackendError, Placement, StabilityReport
from mesh2brick.model import BrickModel, BuildStep, ColorInfo, PlacedPart
from mesh2brick.voxel.grid import EMPTY, VoxelGrid

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from multiprocessing.connection import Connection
    from pathlib import Path

    import trimesh
    from legolization.layout import Layout
    from numpy.typing import NDArray

    from mesh2brick.config import Settings
    from mesh2brick.voxel.color import ColorQuantizer
    from mesh2brick.voxel.grid import HeightUnit

NAME: Final = "legolization"
VERSION: Final = importlib.metadata.version("legolization")

# Fields of PipelineConfig that mesh2brick derives from its own settings; they
# cannot also be set through placement.backend_options.
_MANAGED_FIELDS: Final = frozenset(
    {
        "strategy",
        "seed",
        "hollow",
        "shell_studs",
        "shell_plates",
        "slopes",
        "tiles",
        "repair",
        "repair_config",
        "instructions",
        "plates_per_voxel",
        "progress",
    }
)
_DEFAULT_STEP_SPREAD: Final = 3
AUTO_THOROUGH_MAX_PARTS: Final = 500
"""``steps.sequencing: auto`` uses stability-checked steps up to this size."""
PLACE_BUDGET_SHARE: Final = 0.25
"""Default share of ``placement.time_limit_s`` for legolization's placement
and repair (``time_budget_s``), unless set in ``placement.backend_options``."""
MIN_SEQUENCING_S: Final = 5.0
_TIME_FALLBACK_NOTE: Final = (
    "time limit reached during step planning; steps follow layer order "
    "(raise placement.time_limit_s for stability-checked steps)"
)
_LAYER_PLAN_WARNING: Final = (
    "steps follow layer order without stability checks "
    "(steps.sequencing=layers); support overhangs by hand"
)
LP_ATTEMPT_TIME_LIMIT_S: Final = 5.0
"""Wall-clock limit for every LP attempt except the last (local patch)."""


def _limit_lp_attempts() -> None:
    """Give legolization's LP attempts a time limit (idempotent local patch).

    Raises:
        BackendError: if legolization changed in a way the patch does not expect.
    """
    attempts = getattr(_lego_solver, "_LP_ATTEMPTS", None)
    if not isinstance(attempts, tuple) or len(attempts) < 2:  # noqa: PLR2004
        msg = (
            f"legolization {VERSION}: unexpected LP attempt table; "
            "revisit the local patch in backends/legolization.py"
        )
        raise BackendError(msg)
    patched = (
        *(
            (method, {**(options or {}), "time_limit": LP_ATTEMPT_TIME_LIMIT_S})
            for method, options in attempts[:-1]
        ),
        attempts[-1],
    )
    _lego_solver._LP_ATTEMPTS = patched  # documented local patch
    _lego_solver.__dict__["highspy"] = _HIGHSPY_SHIM


class TimeLimitedHighs(highspy.Highs):
    """``Highs`` that limits every run but the last of legolization's attempts.

    legolization's direct path runs up to three attempts on one instance;
    runs 1 and 2 get :data:`LP_ATTEMPT_TIME_LIMIT_S`, later runs no limit,
    so a solution is still found whenever HiGHS can find one.
    """

    final_attempt: int = 3

    def run(self) -> highspy.HighsStatus:
        """Run HiGHS with a per-attempt time limit."""
        runs = self.__dict__.get("_runs", 0) + 1
        self.__dict__["_runs"] = runs
        limit = LP_ATTEMPT_TIME_LIMIT_S if runs < self.final_attempt else math.inf
        self.setOptionValue("time_limit", self.getRunTime() + limit)
        status: highspy.HighsStatus = super().run()
        return status


class _HighspyShim(types.ModuleType):
    """The ``highspy`` module as legolization's solver sees it after the patch."""

    Highs = TimeLimitedHighs

    def __getattr__(self, name: str) -> object:
        return getattr(highspy, name)


_HIGHSPY_SHIM: Final = _HighspyShim("highspy")
_limit_lp_attempts()


@dataclass(frozen=True, slots=True)
class _Native:
    """What we keep of legolization's result to export without a round trip."""

    layout: Layout
    plan: InstructionPlan | None


class LegolizationBackend:
    """Placer, StabilityChecker, StepSequencer and Exporter via legolization."""

    name: str = NAME

    def __init__(self, progress: Callable[[str], None] | None = None) -> None:
        """Create the backend; ``progress`` receives human-readable status lines."""
        self._progress = progress

    # ------------------------------------------------------------ Placer
    def strategies(self) -> tuple[str, ...]:
        """Placement strategies registered in legolization."""
        return tuple(strategy_names())

    def place(
        self,
        grid: VoxelGrid,
        settings: Settings,
        *,
        name: str = "model",
        deadline: float | None = None,
    ) -> Placement:
        """Place, repair and sequence ``grid`` with legolization.

        legolization's own pipeline runs without its sequencer; steps are
        planned afterwards (:meth:`_plan`) so their cost can be bounded by
        ``deadline`` (a :func:`time.monotonic` timestamp).

        Raises:
            BackendError: on invalid settings or if the grid is empty.
        """
        if grid.filled_count == 0:
            msg = "the voxel grid is empty; nothing to place"
            raise BackendError(msg)
        config = self.pipeline_config(settings, height_unit=grid.height_unit)
        lego_grid = to_lego_grid(grid)
        try:
            result = run(lego_grid, config)
        except ValueError as error:
            raise BackendError(f"legolization rejected the input: {error}") from error
        plan, notes = self._plan(result.layout, config, settings, deadline)
        native = _Native(layout=result.layout, plan=plan)
        return Placement(
            model=to_brick_model(
                result.layout,
                plan,
                name=name,
                source=(
                    f"{NAME} {VERSION}, strategy {config.strategy}, seed {config.seed}"
                ),
            ),
            stability=_report_from_result(result),
            backend=NAME,
            native=native,
            notes=tuple(notes),
        )

    def _plan(
        self,
        layout: Layout,
        config: PipelineConfig,
        settings: Settings,
        deadline: float | None,
    ) -> tuple[InstructionPlan, list[str]]:
        """Choose and run the step planner within the remaining time."""
        mode = settings.steps.sequencing
        notes: list[str] = []
        if mode == "auto":
            mode = "thorough" if len(layout) <= AUTO_THOROUGH_MAX_PARTS else "layers"
            if mode == "layers":
                notes.append(
                    f"{len(layout)} parts: steps follow layer order (stability-checked "
                    f"steps are used up to {AUTO_THOROUGH_MAX_PARTS} parts; "
                    "steps.sequencing=thorough forces them)"
                )
        if mode == "layers":
            return layer_plan(layout, config.instructions), notes
        smart = dataclasses.replace(
            config.instructions, mode="smart", solver=config.solver
        )
        budget = None
        if deadline is not None:
            budget = deadline - time.monotonic() - export_reserve_s(len(layout))
            if budget < MIN_SEQUENCING_S:
                notes.append(_TIME_FALLBACK_NOTE)
                return layer_plan(layout, config.instructions), notes
        self._say(
            "planning stability-checked steps"
            + (f" (up to {budget:.0f} s)" if budget is not None else "")
        )
        plan = plan_with_timeout(layout, smart, budget)
        if plan is None:
            notes.append(_TIME_FALLBACK_NOTE)
            return layer_plan(layout, config.instructions), notes
        return plan, notes

    # ------------------------------------------------------------ StabilityChecker
    def check(self, placement: Placement, settings: Settings) -> StabilityReport:
        """Re-run legolization's rigid-block-equilibrium analysis."""
        native = _native_of(placement)
        config = self.pipeline_config(settings)
        return _report(native.layout, analyze(native.layout, config.solver))

    # ------------------------------------------------------------ StepSequencer
    def sequence(self, placement: Placement, settings: Settings) -> Placement:
        """Recompute build steps with the current step settings."""
        native = _native_of(placement)
        config = self.pipeline_config(settings)
        plan = plan_instructions(
            native.layout,
            config=replace(config.instructions, solver=config.solver),
        )
        return replace(
            placement,
            model=to_brick_model(
                native.layout,
                plan,
                name=placement.model.name,
                source=placement.model.source,
            ),
            native=_Native(layout=native.layout, plan=plan),
        )

    # ------------------------------------------------------------ Exporter
    def write_instructions(
        self,
        placement: Placement,
        path: Path,
        images: Sequence[bytes | None],
        *,
        page_size: Literal["A4", "letter"] = "A4",
        steps_per_page: int = 2,
    ) -> Path:
        """Write legolization's instruction booklet (PDF or HTML by suffix).

        ``images`` holds one PNG per build step (``placement.model.steps``);
        ``None`` entries become placeholder boxes.

        Raises:
            BackendError: without a step plan or with a wrong image count.
        """
        native = _native_of(placement)
        if native.plan is None:
            msg = "instructions need a step plan (smart sequencing)"
            raise BackendError(msg)
        if len(images) != len(native.plan.steps):
            msg = f"{len(images)} step images for {len(native.plan.steps)} steps"
            raise BackendError(msg)
        model, stability = placement.model, placement.stability
        stats = ModelStats(
            name=model.name,
            brick_count=model.part_count,
            mass_g=float(native.layout.total_mass_g()),
            step_count=model.step_count,
            stable=stability.stable,
            buildable=stability.buildable,
            component_count=stability.component_count,
            floating_count=stability.floating_count,
        )
        config = BookletConfig(
            steps_per_page=steps_per_page,
            page_size="a4" if page_size == "A4" else "letter",
            title=model.name,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            write_booklet(
                native.plan,
                stats,
                StepImages(images=tuple(images), renderer=None, warnings=()),
                path,
                config=config,
            )
        except ValueError as error:
            raise BackendError(str(error)) from error
        return path

    def verify_ldraw(self, path: Path) -> int:
        """Re-read an LDraw file strictly and return its part count.

        Uses legolization's strict importer: every part must be a known
        catalogue part, axis-aligned, on the stud/plate grid, in a solid
        colour and collision-free. A stand-in for opening the file in an LDraw
        viewer.

        Raises:
            BackendError: listing every problem found.
        """
        try:
            return len(layout_from_ldraw(path))
        except LdrawImportError as error:
            raise BackendError(
                f"{path.name} failed the LDraw check: {error}"
            ) from error

    def write_ldraw(self, placement: Placement, path: Path) -> Path:
        """Write ``.ldr`` or ``.mpd`` (chosen by suffix) with ``0 STEP`` markers.

        Raises:
            BackendError: if the suffix is not ``.ldr``/``.mpd``.
        """
        if path.suffix.lower() not in {".ldr", ".mpd"}:
            msg = f"LDraw output must end in .ldr or .mpd, got {path.name}"
            raise BackendError(msg)
        native = _native_of(placement)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_model(native.layout, path, plan=native.plan)
        return path

    # ------------------------------------------------------------ settings
    def pipeline_config(
        self,
        settings: Settings,
        *,
        height_unit: HeightUnit | None = None,
    ) -> PipelineConfig:
        """Translate mesh2brick settings into a legolization ``PipelineConfig``.

        Raises:
            BackendError: for unknown strategies or invalid backend options.
        """
        placement = settings.placement
        if placement.strategy not in self.strategies():
            valid = ", ".join(self.strategies())
            msg = f"unknown placement strategy {placement.strategy!r}; valid: {valid}"
            raise BackendError(msg)
        unit = height_unit or settings.voxel.height_unit
        plates_per_cell = 3 if unit == "brick" else 1
        wall = settings.voxel.wall_thickness
        categories = set(settings.parts.categories)
        if not {"brick", "plate"} <= categories:
            msg = (
                "the legolization backend always needs bricks and plates; "
                "keep both in parts.categories (custom whitelists: Phase 4)"
            )
            raise BackendError(msg)
        steps = settings.steps
        instructions = InstructionsConfig(
            # legolization's pipeline never sequences; place() plans the steps
            # itself so their cost can be bounded (see _plan).
            mode="layer",
            target_step_size=steps.parts_per_step,
            max_step_size=steps.parts_per_step + _DEFAULT_STEP_SPREAD,
            min_step_size=min(_DEFAULT_STEP_SPREAD, steps.parts_per_step),
            subassemblies=steps.submodels and steps.sequencing != "layers",
            beam_width=1 if steps.sequencing == "fast" else 4,
            fallback="band" if steps.sequencing == "fast" else "disassembly",
        )
        if not steps.keep_symmetry:
            self._say(
                "note: legolization always keeps mirror-symmetric halves together; "
                "steps.keep_symmetry=false has no effect"
            )
        managed: dict[str, Any] = {
            "strategy": placement.strategy,
            "seed": placement.seed,
            "hollow": settings.voxel.fill == "hollow",
            "shell_studs": wall,
            "shell_plates": wall * plates_per_cell,
            "slopes": "preserve" if "slope" in categories else False,
            "tiles": "tile" in categories,
            "repair": settings.stability.enabled,
            "repair_config": RepairConfig(
                max_rounds=settings.stability.max_repair_iterations
            ),
            "instructions": instructions,
            "progress": self._progress,
        }
        options = _backend_options(placement.backend_options)
        options.setdefault(
            "time_budget_s", round(PLACE_BUDGET_SHARE * placement.time_limit_s)
        )
        return PipelineConfig(**managed, **options)

    def _say(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)


def export_reserve_s(parts: int) -> float:
    """Seconds to keep free after sequencing for LDraw, BOMs and the PDF."""
    return 20.0 + 0.03 * parts


def plan_with_timeout(
    layout: Layout, config: InstructionsConfig, seconds: float | None
) -> InstructionPlan | None:
    """Run legolization's step planner, stopped after ``seconds`` (None = no limit).

    The planner cannot be interrupted in-process, so a limited run happens in
    a child process that is terminated on timeout. Returns ``None`` then.
    """
    if seconds is None:
        return plan_instructions(layout, config=config)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(
        target=_plan_worker, args=(layout, config, sender), daemon=True
    )
    worker.start()
    sender.close()
    try:
        if receiver.poll(max(seconds, 0.0)):
            plan = receiver.recv()
            if isinstance(plan, BaseException):
                raise BackendError(f"step planning failed: {plan}") from plan
            return cast("InstructionPlan", plan)
        return None
    except EOFError as error:
        msg = "step planning process ended without a result"
        raise BackendError(msg) from error
    finally:
        receiver.close()
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=10)


def _plan_worker(
    layout: Layout, config: InstructionsConfig, sender: Connection
) -> None:
    """Child-process entry point: plan and send the result (or the error)."""
    try:
        sender.send(plan_instructions(layout, config=config))
    except Exception as error:
        sender.send(error)
    finally:
        sender.close()


def layer_plan(layout: Layout, config: InstructionsConfig) -> InstructionPlan:
    """Bottom-up layer chunks as build steps, without stability checks.

    Uses legolization's own chunking (spatially coherent groups of about
    ``target_step_size`` parts per layer). Layer order is always insertable
    from above; overhangs may need a supporting hand, which the plan says.
    """
    chunks = chunk_bands(layout, config=config, pairs=mirror_pairs(layout))
    steps = tuple(
        LegoStep(
            index=index,
            brick_ids=tuple(brick_ids),
            prefix_stable=True,
            prefix_max_score=0.0,
        )
        for index, (_band, brick_ids) in enumerate(chunks, start=1)
    )
    plan = InstructionPlan(
        steps=steps,
        warnings=(_LAYER_PLAN_WARNING,),
        bom=bill_of_materials(layout),
    )
    return dataclasses.replace(plan, bom=bill_of_materials(layout, plan=plan))


# ---------------------------------------------------------------- palette
def solid_color_codes() -> frozenset[int]:
    """LDraw codes of the opaque solid palette that placement accepts."""
    return frozenset(int(code) for code in default_palette().codes)


def color_info(codes: Iterable[int]) -> dict[int, ColorInfo]:
    """Name and display colour for each LDraw code.

    Raises:
        BackendError: for codes outside the solid palette.
    """
    palette = default_palette()
    if unknown := sorted(set(codes) - solid_color_codes()):
        msg = (
            f"LDraw colour code(s) {unknown} are not solid colours in the local "
            "LDraw library (see ldraw.org colour chart)"
        )
        raise BackendError(msg)
    result: dict[int, ColorInfo] = {}
    for code in sorted(set(codes)):
        r, g, b = palette.rgb_of(code)
        result[code] = ColorInfo(
            name=palette.name_of(code), rgb_hex=f"#{r:02x}{g:02x}{b:02x}"
        )
    return result


QUANTIZE_CHUNK: Final = 8192
"""Colours matched per batch (legolization builds an n x palette matrix)."""


def color_quantizer(codes: Iterable[int] | None = None) -> ColorQuantizer:
    """Nearest-colour matcher onto ``codes`` (default: the whole solid palette).

    Uses legolization's palette metric (Oklab with over-weighted chroma, so
    greys stay grey and black stays black).

    Raises:
        BackendError: if ``codes`` contains no solid palette colour.
    """
    palette = default_palette()
    if codes is not None:
        wanted = np.asarray(sorted(set(codes) & solid_color_codes()), dtype=np.int64)
        if not len(wanted):
            msg = "the colour palette is empty (no solid LDraw colour allowed)"
            raise BackendError(msg)
        index = np.searchsorted(np.asarray(palette.codes, dtype=np.int64), wanted)
        palette = Palette(
            codes=palette.codes[index],
            rgbs=palette.rgbs[index],
            names=tuple(palette.names[int(i)] for i in index),
            oklabs=palette.oklabs[index],
        )

    def quantize(rgb: NDArray[np.uint8], /) -> NDArray[np.int32]:
        values = np.asarray(rgb, dtype=np.float64).reshape(-1, 3)
        result = np.empty(len(values), dtype=np.int32)
        for start in range(0, len(values), QUANTIZE_CHUNK):
            chunk = values[start : start + QUANTIZE_CHUNK]
            result[start : start + len(chunk)] = palette.quantize(chunk)
        return result

    return quantize


def color_rgb(codes: Iterable[int]) -> dict[int, tuple[int, int, int]]:
    """RGB triple per LDraw code (for ``.vox`` export)."""
    return {code: _hex_to_rgb(info.rgb_hex) for code, info in color_info(codes).items()}


def _hex_to_rgb(text: str) -> tuple[int, int, int]:
    value = int(text.removeprefix("#"), 16)
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


# ---------------------------------------------------------------- reference voxelizer
def reference_voxelize(
    mesh: trimesh.Trimesh, *, pitch_mm: float, color: int = 7
) -> VoxelGrid:
    """Legolization's own mesh voxelizer, as a benchmark reference.

    It voxelizes the surface at plate resolution and floods the inside, without
    volume fractions; the result is a plate-unit grid.
    """
    lego_grid = grid_from_mesh(
        mesh, options=MeshOptions(pitch=pitch_mm, up="z", colour_code=color)
    )
    return from_lego_grid(lego_grid, height_unit="plate", pitch_mm=pitch_mm)


# ---------------------------------------------------------------- conversions
def to_lego_grid(grid: VoxelGrid) -> LegoGrid:
    """Resample our grid to legolization's plate-layer grid (codes validated).

    Raises:
        BackendError: if a colour code is not in the solid LDraw palette.
    """
    try:
        return LegoGrid.from_array(
            grid.to_codes(), plates_per_voxel=grid.plates_per_cell
        )
    except ValueError as error:
        raise BackendError(str(error)) from error


def from_lego_grid(
    lego_grid: LegoGrid,
    *,
    height_unit: HeightUnit = "plate",
    pitch_mm: float = 8.0,
) -> VoxelGrid:
    """Convert a legolization plate-layer grid back into our grid.

    With ``height_unit="brick"`` every three plate layers must be identical.

    Raises:
        BackendError: if the layers cannot be merged into bricks.
    """
    codes = np.asarray(lego_grid.codes, dtype=np.int32)
    # legolization's IGNORE (-2, filled but colour-free) has no meaning for us.
    if np.any(codes < EMPTY):
        msg = "grid contains colour-free (IGNORE) cells; convert before hollowing"
        raise BackendError(msg)
    if height_unit == "brick":
        if codes.shape[2] % 3:
            msg = f"{codes.shape[2]} plate layers do not form whole bricks"
            raise BackendError(msg)
        stacked = codes.reshape(*codes.shape[:2], -1, 3)
        if np.any(stacked != stacked[..., :1]):
            msg = "plate layers differ within a brick height"
            raise BackendError(msg)
        codes = stacked[..., 0]
    return VoxelGrid.from_codes(codes, height_unit=height_unit, pitch_mm=pitch_mm)


def load_voxel_file(path: Path, *, height_unit: HeightUnit = "brick") -> VoxelGrid:
    """Read a MagicaVoxel ``.vox`` or ``.npy`` file with legolization's loader.

    One file voxel becomes one cell of ``height_unit``; RGB colours are
    quantised to the nearest solid LDraw colour by legolization.

    Raises:
        BackendError: if the file cannot be read.
    """
    suffix = path.suffix.lower()
    try:
        match suffix:
            case ".vox":
                lego_grid = LegoGrid.from_vox(path, plates_per_voxel=1)
            case ".npy":
                lego_grid = LegoGrid.from_npy(path, plates_per_voxel=1)
            case _:
                msg = f"unsupported voxel file {path.name} (expected .vox or .npy)"
                raise BackendError(msg)
    except (OSError, ValueError) as error:
        raise BackendError(f"cannot read {path}: {error}") from error
    codes = np.asarray(lego_grid.codes, dtype=np.int32)
    return VoxelGrid.from_codes(codes, height_unit=height_unit)


def to_brick_model(
    layout: Layout,
    plan: InstructionPlan | None,
    *,
    name: str,
    source: str = "",
) -> BrickModel:
    """Convert legolization's layout + plan into a :class:`BrickModel`."""
    step_of: dict[int, int] = {}
    steps: tuple[BuildStep, ...] = ()
    if plan is not None:
        for index, step in enumerate(plan.steps):
            for brick_id in step.brick_ids:
                step_of.setdefault(brick_id, index)
        steps = tuple(
            BuildStep(submodel=step.submodel, attaches=step.attaches)
            for step in plan.steps
        )
    if not step_of:
        # No plan: one step per occupied layer (what the plain .ldr writer does).
        layers = sorted({brick.layer for brick in layout})
        layer_step = {layer: i for i, layer in enumerate(layers)}
        step_of = {b.brick_id: layer_step[b.layer] for b in layout}
        steps = tuple(BuildStep() for _ in layers)
    missing = [b.brick_id for b in layout if b.brick_id not in step_of]
    if missing:
        msg = f"{len(missing)} bricks are not part of any build step"
        raise BackendError(msg)
    palette = default_palette()
    parts: list[PlacedPart] = []
    colors: dict[int, ColorInfo] = {}
    for brick in sorted(
        layout, key=lambda b: (step_of[b.brick_id], b.layer, b.brick_id)
    ):
        part = layout.part_of(brick)
        code = int(brick.colour_code)
        if code not in colors:
            r, g, b = palette.rgb_of(code)
            colors[code] = ColorInfo(
                name=palette.name_of(code), rgb_hex=f"#{r:02x}{g:02x}{b:02x}"
            )
        parts.append(
            PlacedPart(
                part=part.ldraw_part,
                color=code,
                x=brick.x,
                y=brick.y,
                layer=brick.layer,
                yaw=brick.yaw,
                cells=tuple(sorted(layout.cells_of(brick))),
                step=step_of[brick.brick_id],
                category=str(part.category.value),
                backend_key=brick.part_key,
            )
        )
    return BrickModel(
        name=name,
        parts=tuple(parts),
        steps=steps,
        colors=dict(sorted(colors.items())),
        source=source,
    )


# ---------------------------------------------------------------- helpers
def _backend_options(options: dict[str, Any]) -> dict[str, Any]:
    known = {f.name for f in dataclasses.fields(PipelineConfig)}
    unknown = sorted(set(options) - known)
    if unknown:
        msg = (
            f"unknown legolization option(s): {', '.join(unknown)}; "
            f"see PipelineConfig in legolization {VERSION}"
        )
        raise BackendError(msg)
    clashes = sorted(set(options) & _MANAGED_FIELDS)
    if clashes:
        msg = (
            f"placement.backend_options cannot set {', '.join(clashes)}; "
            "use the corresponding mesh2brick setting instead"
        )
        raise BackendError(msg)
    if nested := sorted(set(options) & {"mesh", "weights", "solver"}):
        msg = f"nested backend options are not supported yet: {', '.join(nested)}"
        raise BackendError(msg)
    return dict(options)


def _report_from_result(result: PipelineResult) -> StabilityReport:
    return StabilityReport(
        stable=result.stability.stable,
        component_count=result.component_count,
        floating_count=result.floating_count,
        max_score=float(result.stability.max_score),
        min_capacity_n=float(result.stability.min_capacity),
    )


def _report(layout: Layout, stability: StabilityResult) -> StabilityReport:
    graph = ConnectionGraph.from_layout(layout)
    return StabilityReport(
        stable=stability.stable,
        component_count=graph.component_count(),
        floating_count=len(graph.floating_ids()),
        max_score=float(stability.max_score),
        min_capacity_n=float(stability.min_capacity),
    )


def _native_of(placement: Placement) -> _Native:
    if placement.backend != NAME or not isinstance(placement.native, _Native):
        msg = (
            "this placement was not produced by the legolization backend in this "
            "process (re-import from .ldr is planned)"
        )
        raise BackendError(msg)
    return placement.native
