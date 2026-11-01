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
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final

import numpy as np
from legolization import PipelineConfig, PipelineResult, run
from legolization import VoxelGrid as LegoGrid
from legolization.color import default_palette
from legolization.graph import ConnectionGraph
from legolization.instructions.sequencer import InstructionsConfig, plan_instructions
from legolization.ldraw_out import write_model
from legolization.placement.registry import strategy_names
from legolization.placement.repair import RepairConfig
from legolization.stability.solver import StabilityResult, analyze

from mesh2brick.backends.protocols import BackendError, Placement, StabilityReport
from mesh2brick.model import BrickModel, BuildStep, ColorInfo, PlacedPart
from mesh2brick.voxel.grid import EMPTY, VoxelGrid

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from legolization.instructions.sequencer import InstructionPlan
    from legolization.layout import Layout

    from mesh2brick.config import Settings
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
        self, grid: VoxelGrid, settings: Settings, *, name: str = "model"
    ) -> Placement:
        """Run legolization's full pipeline (place, repair, sequence) on ``grid``.

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
        native = _Native(layout=result.layout, plan=result.plan)
        return Placement(
            model=to_brick_model(
                result.layout,
                result.plan,
                name=name,
                source=(
                    f"{NAME} {VERSION}, strategy {config.strategy}, seed {config.seed}"
                ),
            ),
            stability=_report_from_result(result),
            backend=NAME,
            native=native,
        )

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
            target_step_size=steps.parts_per_step,
            max_step_size=steps.parts_per_step + _DEFAULT_STEP_SPREAD,
            min_step_size=min(_DEFAULT_STEP_SPREAD, steps.parts_per_step),
            subassemblies=steps.submodels,
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
        return PipelineConfig(**managed, **_backend_options(placement.backend_options))

    def _say(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)


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
