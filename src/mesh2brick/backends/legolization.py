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
which solves such LPs in seconds, takes over. The order matters as much as
the limits (docs/benchmarks.md, Roadmap 2 and 1.3.0): simplex solves easy LPs
in well under 3 s, but stalls on slope layouts and never finishes large LPs,
while the interior-point method *without* its final "crossover" solves both
quickly (Duo at 48 studs: 49 s instead of more than an hour; the bunny with
slopes: 70 s instead of 147 s). Both paths therefore run: simplex (3 s), the
interior-point method without crossover (300 s), simplex without presolve
(5 s), and finally legolization's own last attempt without a limit.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import math
import multiprocessing
import re
import time
import types
import warnings
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final, cast

import highspy
import numpy as np
from legolization import MeshOptions, PipelineConfig, run
from legolization import VoxelGrid as LegoGrid
from legolization import pipeline as _lego_pipeline
from legolization.catalog import Catalog, Category, default_catalog
from legolization.color import Palette, default_palette
from legolization.graph import ConnectionGraph
from legolization.instructions.bom import bill_of_materials
from legolization.instructions.chunking import chunk_bands, mirror_pairs
from legolization.instructions.sequencer import (
    BuildStep as LegoStep,
)
from legolization.instructions.sequencer import (
    InstructionPlan,
    InstructionsConfig,
    RotStep,
    plan_instructions,
)
from legolization.layout import CollisionError
from legolization.ldraw_in import LdrawImportError, layout_from_ldraw
from legolization.ldraw_out import write_model
from legolization.mesh import grid_from_mesh
from legolization.placement.merge import resolve_ignore_colours
from legolization.placement.registry import strategy_names
from legolization.placement.repair import RepairConfig
from legolization.stability import solver as _lego_solver
from legolization.stability.solver import StabilityResult, analyze

from mesh2brick.backends.checks import check_states, default_workers
from mesh2brick.backends.protocols import BackendError, Placement, StabilityReport
from mesh2brick.backends.pyldraw import part_exists
from mesh2brick.catalog.rebrickable import available_colors
from mesh2brick.catalog.whitelist import (
    BackendRules,
    PlaceablePart,
    Whitelist,
    allowed_parts,
)
from mesh2brick.model import BrickModel, BuildStep, ColorInfo, PlacedPart
from mesh2brick.place.split import choose_split
from mesh2brick.place.tiles import (
    flat_faces,
    flat_top_plates,
    tile_cover,
    tiled_faces,
)
from mesh2brick.steps.balance import (
    STEP_SPREAD,
    largest_step,
    merge_small_steps,
    split_large_steps,
)
from mesh2brick.steps.budget import (
    LLM_RESERVE_S,
    MIN_SEQUENCING_S,
    choose_planner,
)
from mesh2brick.steps.hanging import attach_hanging
from mesh2brick.steps.plan import PlanStep
from mesh2brick.steps.regroup import merge_ranges
from mesh2brick.steps.structure import Structure
from mesh2brick.voxel.flat import top_cells
from mesh2brick.voxel.grid import EMPTY, PLATES_PER_BRICK, VoxelGrid

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
    from multiprocessing.connection import Connection
    from pathlib import Path

    import trimesh
    from legolization.layout import Layout, PlacedBrick
    from numpy.typing import NDArray

    from mesh2brick.config import Settings, StepsConfig
    from mesh2brick.model import Cell
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
PLACE_BUDGET_SHARE: Final = 0.25
"""Default share of ``placement.time_limit_s`` for legolization's placement
and repair (``time_budget_s``), unless set in ``placement.backend_options``."""
_TIME_FALLBACK_NOTE: Final = (
    "time limit reached before the steps could be checked; steps follow layer "
    "order without stability checks (raise placement.time_limit_s, e.g. --time "
    "20min, to check them)"
)
_SEARCH_FALLBACK_NOTE: Final = (
    "legolization's step search did not finish in time; steps follow layer "
    "order instead and are checked one by one"
)
_LAYER_PLAN_WARNING: Final = (
    "steps follow layer order without stability checks "
    "(steps.sequencing=layers); support overhangs by hand"
)
LP_FIRST_SIMPLEX_S: Final = 3.0
"""Wall-clock limit for the first simplex attempt. Easy LPs finish within it
(longest of 89 measured: 2.3 s); stalled and large ones go on to the
interior-point method (1.3.0, docs/benchmarks.md)."""
LP_ATTEMPT_TIME_LIMIT_S: Final = 5.0
"""Wall-clock limit for the later simplex attempts (local patch)."""
LP_IPM_TIME_LIMIT_S: Final = 300.0
"""Wall-clock limit for the interior-point attempt without crossover."""
IPM_WITHOUT_CROSSOVER: Final = ("highs-ipm", {"run_crossover": "off"})
CHECK_SIMPLEX_MAX_ROWS: Final = 10_000
"""Step-check workers skip the simplex above this LP size (about 460 parts,
21-23 rows per part): on bigger intermediate states it never finished within
its 3 s, on smaller ones it is about as fast as the interior point."""


def skip_simplex_for_large_lps(rows: int | None = CHECK_SIMPLEX_MAX_ROWS) -> None:
    """Send stability LPs above ``rows`` rows straight to the interior point.

    Process-wide; only the step-check workers call it (ADR 0017).
    """
    linprog = _lego_solver.__dict__["linprog"]
    if isinstance(linprog, _QuietLinprog):
        linprog.simplex_max_rows = rows


def _limit_lp_attempts() -> None:
    """Reorder and limit legolization's LP attempts (idempotent local patch).

    The first simplex attempt gets :data:`LP_FIRST_SIMPLEX_S`, then the
    interior-point method without crossover :data:`LP_IPM_TIME_LIMIT_S`,
    the remaining attempts but the last :data:`LP_ATTEMPT_TIME_LIMIT_S`.

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
    if not isinstance(_lego_solver.__dict__.get("linprog"), _QuietLinprog):
        (first, first_options), ipm = attempts[0], IPM_WITHOUT_CROSSOVER
        patched = (
            (first, {**(first_options or {}), "time_limit": LP_FIRST_SIMPLEX_S}),
            (ipm[0], {**ipm[1], "time_limit": LP_IPM_TIME_LIMIT_S}),
            *(
                (method, {**(options or {}), "time_limit": LP_ATTEMPT_TIME_LIMIT_S})
                for method, options in attempts[1:-1]
            ),
            attempts[-1],
        )
        _lego_solver._LP_ATTEMPTS = patched  # documented local patch
        namespace = _lego_solver.__dict__
        namespace["linprog"] = _QuietLinprog(namespace["linprog"])
    _lego_solver.__dict__["highspy"] = _HIGHSPY_SHIM


class _QuietLinprog:
    """scipy's ``linprog`` without its warning for HiGHS-only options.

    scipy passes options it does not know (``run_crossover``) to HiGHS
    verbatim and warns about each call; the option is intended here. With
    ``simplex_max_rows`` set (only in the step-check workers, ADR 0017), the
    simplex attempts are skipped for LPs with more rows: on intermediate
    states above about 460 parts they never finished within their limit
    (measured on the toadstool and the bunny: 3 s lost per state).
    """

    simplex_max_rows: int | None = None

    def __init__(self, linprog: Callable[..., Any]) -> None:
        self._linprog = linprog

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        limit = self.simplex_max_rows
        a_ub = kwargs.get("A_ub")
        if (
            limit is not None
            and kwargs.get("method") == "highs"
            and a_ub is not None
            and a_ub.shape[0] > limit
        ):
            return types.SimpleNamespace(
                success=False, status=1, x=None, message="simplex skipped (large LP)"
            )
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", re.escape("Unrecognized options detected: {'run_crossover'")
            )
            return self._linprog(*args, **kwargs)


class TimeLimitedHighs(highspy.Highs):
    """``Highs`` with the attempt order and limits of the scipy path.

    legolization's direct path runs up to three attempts on one instance
    (simplex, simplex without presolve, interior point). Run 1 gets
    :data:`LP_FIRST_SIMPLEX_S` and, if that does not solve the LP, continues
    with the interior-point method without crossover; run 2 gets
    :data:`LP_ATTEMPT_TIME_LIMIT_S`, run 3 no limit, so a solution is still
    found whenever HiGHS can find one.
    """

    final_attempt: int = 3

    def run(self) -> highspy.HighsStatus:
        """Run HiGHS with the per-attempt limits."""
        runs = self.__dict__.get("_runs", 0) + 1
        self.__dict__["_runs"] = runs
        if runs == 1:
            status = self._run_limited(LP_FIRST_SIMPLEX_S)
            if self.getModelStatus() == highspy.HighsModelStatus.kOptimal:
                return status
            return self._run_ipm_without_crossover()
        limit = LP_ATTEMPT_TIME_LIMIT_S if runs < self.final_attempt else math.inf
        return self._run_limited(limit)

    def _run_limited(self, seconds: float) -> highspy.HighsStatus:
        self.setOptionValue("time_limit", self.getRunTime() + seconds)
        status: highspy.HighsStatus = super().run()
        return status

    def _run_ipm_without_crossover(self) -> highspy.HighsStatus:
        _, solver = self.getOptionValue("solver")  # (status, value)
        _, crossover = self.getOptionValue("run_crossover")
        self.setOptionValue("solver", "ipm")
        self.setOptionValue("run_crossover", "off")
        try:
            return self._run_limited(LP_IPM_TIME_LIMIT_S)
        finally:
            self.setOptionValue("solver", solver)
            self.setOptionValue("run_crossover", crossover)


class _HighspyShim(types.ModuleType):
    """The ``highspy`` module as legolization's solver sees it after the patch."""

    Highs = TimeLimitedHighs

    def __getattr__(self, name: str) -> object:
        return getattr(highspy, name)


_HIGHSPY_SHIM: Final = _HighspyShim("highspy")
_limit_lp_attempts()


# ---------------------------------------------------------------- part whitelist
PLACEABLE_CATEGORIES: Final = ("brick", "plate", "tile", "slope")
"""legolization categories its strategies place; the others (special, snot)
only serve LDraw import and stay untouched."""
FILLER_PARTS: Final = frozenset({"3005", "3024"})


def is_finishing_tile(part: Any) -> bool:
    """One of legolization's tiles it lists for import only (``special``).

    Its catalogue has tiles 1 x 3, 1 x 6, 1 x 8, 2 x 4 and 2 x 6 with full
    geometry but places only 1 x 1, 1 x 2, 1 x 4 and 2 x 2; mesh2brick's tile
    pass uses all nine (ROADMAP 9, ADR 0020).
    """
    return (
        part.category is Category.SPECIAL
        and part.key.startswith("tile_")
        and part.height_plates == 1
        and not part.top_connectors
        and part.mount_normal is None
    )


def part_category(part: Any) -> str:
    """mesh2brick's family of a legolization part (finishing tiles are tiles)."""
    return "tile" if is_finishing_tile(part) else str(part.category.value)


def placeable_parts() -> tuple[PlaceablePart, ...]:
    """Parts legolization or the tile pass can place, one per LDraw number."""
    found: dict[str, PlaceablePart] = {}
    for part in default_catalog().parts.values():
        category = part_category(part)
        if category in PLACEABLE_CATEGORIES and part.ldraw_part not in found:
            found[part.ldraw_part] = PlaceablePart(
                part=part.ldraw_part,
                category=cast("Any", category),
            )
    return tuple(sorted(found.values(), key=lambda p: (p.category, p.part)))


def placement_footprint(part: str) -> tuple[int, int, int]:
    """Footprint ``(width, length, height_plates)`` in legolization's cell model.

    Used to cross-check the specs derived from the LDraw geometry.

    Raises:
        BackendError: if ``part`` is not placeable.
    """
    for entry in default_catalog().parts.values():
        if entry.ldraw_part == part and part_category(entry) in PLACEABLE_CATEGORIES:
            cells = entry.occupied_cells
            sides = sorted(
                (
                    max(c[0] for c in cells) - min(c[0] for c in cells) + 1,
                    max(c[1] for c in cells) - min(c[1] for c in cells) + 1,
                )
            )
            return (sides[0], sides[1], entry.height_plates)
    msg = f"part {part} is not placeable by legolization"
    raise BackendError(msg)


def backend_rules() -> BackendRules:
    """What legolization 0.5.0 cannot do without (measured, ADR 0009).

    It looks up the 1 x 1 brick and plate by name to fill any shape, and its
    slope pass uses all three slopes by name.
    """
    slopes = frozenset(p.part for p in placeable_parts() if p.category == "slope")
    reasons = dict.fromkeys(
        FILLER_PARTS, "legolization fills arbitrary shapes with 1 x 1 brick and plate"
    )
    reasons |= dict.fromkeys(slopes, "legolization's slope pass uses all its slopes")
    return BackendRules(required=FILLER_PARTS, coupled=(slopes,), reasons=reasons)


def whitelist(settings: Settings) -> Whitelist:
    """The part set ``settings.parts`` allows (see catalog.whitelist).

    Raises:
        WhitelistError: for impossible part settings.
    """
    return allowed_parts(
        placeable_parts(), settings.parts, backend_rules(), in_library=part_exists
    )


def restricted_catalog(parts: frozenset[str]) -> Catalog:
    """Legolization's catalogue with only ``parts`` among the placeable ones."""
    full = default_catalog()
    return Catalog(
        parts={
            key: part
            for key, part in full.parts.items()
            if part.category.value not in PLACEABLE_CATEGORIES
            or part.ldraw_part in parts
        }
    )


# ---------------------------------------------------------------- colour availability
@dataclass(frozen=True, slots=True)
class SplitReport:
    """What :func:`split_unavailable` changed."""

    replaced: int = 0
    """Bricks replaced by shorter ones."""
    added: int = 0
    """Bricks that took their place."""
    unresolved: tuple[tuple[str, int], ...] = ()
    """(LDraw part, colour) pairs that could not be replaced."""


def produced_in(part: str, colour: int) -> bool | None:
    """Whether LEGO makes ``part`` in ``colour`` (``None``: unknown)."""
    colours = available_colors(part)
    return None if colours is None else colour in colours


def unavailable_parts(
    colours: Iterable[int],
    settings: Settings,
    produced: Callable[[str, int], bool | None] = produced_in,
) -> frozenset[str]:
    """Enabled placeable parts LEGO does not make in one of ``colours``.

    The 1 x 1 fillers stay (legolization cannot do without them); a coupled
    group (the slopes) goes completely if one member has to go.
    """
    used = tuple(colours)
    rules = backend_rules()
    enabled = set(settings.parts.categories)
    gone = {
        p.part
        for p in placeable_parts()
        if p.category in enabled
        and p.part not in rules.required
        and any(produced(p.part, c) is False for c in used)
    }
    for group in rules.coupled:
        if gone & group and "slope" in settings.parts.categories:
            gone |= group
    return frozenset(gone)


Piece = tuple[str, int]
"""(LDraw part, LDraw colour) of one part in a replacement."""


def replacement_options(
    part: str,
    colour: int,
    colours: Iterable[int],
    *,
    nearest: int = 2,
    produced: Callable[[str, int], bool | None] = produced_in,
) -> tuple[tuple[Piece, ...], ...]:
    """Ways to replace ``part`` in ``colour``, which LEGO does not make.

    First, shorter parts of the same family, width, height and colour, split
    along the long side (fewest pieces, :func:`choose_split`); then the same
    part in the ``nearest`` colours of ``colours`` LEGO makes it in (closest
    by RGB). Every option uses only parts produced in their colour.

    Raises:
        BackendError: if ``part`` is not placeable.
    """
    width, length, height = placement_footprint(part)
    category = next(p.category for p in placeable_parts() if p.part == part)
    options: list[tuple[Piece, ...]] = []
    lengths: dict[int, str] = {}
    for other in placeable_parts():
        if other.category != category or other.part == part:
            continue
        w, long, h = placement_footprint(other.part)
        if (w, h) == (width, height) and long < length and produced(other.part, colour):
            lengths.setdefault(long, other.part)
    split = choose_split(length, lengths)
    if split is not None and len(split) > 1:
        options.append(tuple((lengths[piece], colour) for piece in split))
    known = available_colors(part) or frozenset()
    candidates = sorted(set(colours) & known - {colour})
    if candidates:
        rgb = color_rgb([colour, *candidates])
        target = np.array(rgb[colour], dtype=float)
        candidates.sort(key=lambda c: float(np.linalg.norm(np.array(rgb[c]) - target)))
        options.extend(((part, c),) for c in candidates[:nearest])
    return tuple(options)


def _rect_dims(part: Any) -> tuple[int, int, int] | None:
    """(width, length, height) of a full-rectangle part, else ``None``."""
    cells = part.occupied_cells
    xs = {c[0] for c in cells}
    ys = {c[1] for c in cells}
    zs = {c[2] for c in cells}
    if len(cells) != len(xs) * len(ys) * len(zs):
        return None
    width, length = sorted((len(xs), len(ys)))
    return (width, length, len(zs))


def split_unavailable(
    layout: Layout, produced: Callable[[str, int], bool | None] = produced_in
) -> SplitReport:
    """Replace bricks/plates LEGO does not make in their colour (in place).

    Each is split along its long side into shorter parts of the same width,
    height, family and colour that exist (two 1-wide rows as a fallback for
    2-wide parts), with joints away from the joints directly above and below
    (:func:`mesh2brick.place.split.choose_split`). Only parts of
    ``layout.catalog`` are used, so whitelists still hold.
    """
    pieces = _split_pieces(layout, produced)
    replaced = added = 0
    unresolved: list[tuple[str, int]] = []
    for brick in list(layout):
        part = layout.part_of(brick)
        if produced(part.ldraw_part, brick.colour_code) is not False:
            continue
        new = _replace_brick(layout, brick, pieces)
        if new is None:
            unresolved.append((part.ldraw_part, brick.colour_code))
        else:
            replaced += 1
            added += new
    return SplitReport(replaced=replaced, added=added, unresolved=tuple(unresolved))


_PieceKey = tuple[str, int, int, int]  # (category, width, height, colour)


def _split_pieces(
    layout: Layout, produced: Callable[[str, int], bool | None]
) -> Callable[[_PieceKey], dict[int, str]]:
    """Lookup (category, width, height, colour) -> {length: part key}."""
    shapes: list[tuple[str, int, int, int, str, str]] = []
    for key, part in layout.catalog.parts.items():
        category = part.category.value
        dims = _rect_dims(part)
        if category in ("brick", "plate") and dims is not None:
            shapes.append((category, dims[0], dims[1], dims[2], key, part.ldraw_part))
    memo: dict[_PieceKey, dict[int, str]] = {}

    def lookup(wanted: _PieceKey) -> dict[int, str]:
        if wanted not in memo:
            category, width, height, colour = wanted
            memo[wanted] = {
                length: key
                for cat, w, length, h, key, ldraw in sorted(shapes)
                if (cat, w, h) == (category, width, height)
                and produced(ldraw, colour) is not False
            }
        return memo[wanted]

    return lookup


def _replace_brick(
    layout: Layout,
    brick: PlacedBrick,
    pieces: Callable[[_PieceKey], dict[int, str]],
) -> int | None:
    """Swap ``brick`` for existing shorter parts; number added or ``None``."""
    part = layout.part_of(brick)
    cells = layout.cells_of(brick)
    if part.category.value not in ("brick", "plate") or _rect_dims(part) is None:
        return None
    xs = sorted({c[0] for c in cells})
    ys = sorted({c[1] for c in cells})
    layers = sorted({c[2] for c in cells})
    axis = 0 if len(xs) >= len(ys) else 1
    along, across = (xs, ys) if axis == 0 else (ys, xs)
    category = part.category.value
    plan = None
    for rows in ([across], [[a] for a in across]):  # whole width, then 1-wide rows
        plan = _strip_plan(
            layout,
            brick,
            along=along,
            rows=rows,
            axis=axis,
            layers=layers,
            pieces=pieces,
            category=category,
        )
        if plan is not None or len(across) == 1:
            break
    if plan is None:
        return None
    layout.remove(brick.brick_id)
    added: list[int] = []
    for key, target in plan:
        placed = _place_exact(layout, key, target, layers[0], brick.colour_code)
        if placed is None:
            layout.remove_many(added)
            layout.add(
                brick.part_key,
                brick.x,
                brick.y,
                brick.layer,
                brick.yaw,
                brick.colour_code,
            )
            return None
        added.append(placed)
    return len(added)


def _strip_plan(
    layout: Layout,
    brick: PlacedBrick,
    *,
    along: list[int],
    rows: list[list[int]],
    axis: int,
    layers: list[int],
    pieces: Callable[[_PieceKey], dict[int, str]],
    category: str,
) -> list[tuple[str, frozenset[tuple[int, int, int]]]] | None:
    """Split plan for ``rows`` (each a set of cross coordinates) or ``None``."""
    plan: list[tuple[str, frozenset[tuple[int, int, int]]]] = []
    for row in rows:
        available = pieces((category, len(row), len(layers), brick.colour_code))
        avoid = _neighbour_joints(layout, along, row, axis, layers)
        split = choose_split(len(along), available, avoid)
        if split is None:
            return None
        start = 0
        for piece in split:
            span = along[start : start + piece]
            target = frozenset(
                (a, c, z) if axis == 0 else (c, a, z)
                for a in span
                for c in row
                for z in layers
            )
            plan.append((available[piece], target))
            start += piece
    return plan


def _neighbour_joints(
    layout: Layout, along: list[int], row: list[int], axis: int, layers: list[int]
) -> set[int]:
    """Offsets along the brick where bricks directly above or below meet."""
    found: set[int] = set()
    for z in (layers[0] - 1, layers[-1] + 1):
        for c in row:
            ids = []
            for a in along:
                cell = (a, c, z) if axis == 0 else (c, a, z)
                hit = layout.brick_at(cell)
                ids.append(None if hit is None else hit.brick_id)
            found.update(
                i
                for i in range(1, len(ids))
                if ids[i] is not None
                and ids[i - 1] is not None
                and ids[i] != ids[i - 1]
            )
    return found


def _place_exact(
    layout: Layout,
    key: str,
    target: frozenset[tuple[int, int, int]],
    layer: int,
    colour: int,
) -> int | None:
    """Add ``key`` so it covers exactly ``target``; its brick id or ``None``."""
    part = layout.catalog[key]
    tx = min(c[0] for c in target)
    ty = min(c[1] for c in target)
    for yaw in part.orientations:
        cells = part.cells_at(0, 0, layer, yaw)
        x = tx - min(c[0] for c in cells)
        y = ty - min(c[1] for c in cells)
        if frozenset(part.cells_at(x, y, layer, yaw)) == target:
            try:
                return layout.add(key, x, y, layer, yaw, colour).brick_id
            except CollisionError:
                return None
    return None


# ---------------------------------------------------------------- tiles (ROADMAP 9)
TILE_CHECK_BASE_S: Final = 10.0
TILE_CHECK_PER_PART_S: Final = 0.02
"""Changes that make parts heavier are followed by a stability check of the
whole model, while the steps are planned (measured: 3 s for 189 parts, 14 s
for 776, 33 s for 1,682, 65 s for 2,209). With less time left than
:func:`tile_check_s` only the changes that make parts lighter are made; a
check that runs longer than that eats into the time kept for the export."""
_TILES_UNCHECKED_NOTE: Final = (
    "tiles skipped: the time limit stopped the stability check, so the tiles "
    "could not be checked either (raise placement.time_limit_s)"
)
_TILES_UNDONE_NOTE: Final = (
    "tiles undone: with them the model would no longer hold together"
)
_MASS_EPS: Final = 1e-9


def tile_check_s(parts: int) -> float:
    """Seconds to keep for the stability check after the tile pass."""
    return TILE_CHECK_BASE_S + TILE_CHECK_PER_PART_S * parts


@dataclass(frozen=True, slots=True)
class _Tiling:
    """What the tile pass did in :meth:`LegolizationBackend.place`.

    ``check`` is the running stability check of the tiled model (``None``:
    not needed); ``before`` the layout to go back to if it fails.
    """

    notes: tuple[str, ...] = ()
    before: Layout | None = None
    check: Future[StabilityReport] | None = None


@dataclass(frozen=True, slots=True)
class _Steps:
    """A step plan with its pre-assembly units, check flags and notes."""

    plan: InstructionPlan
    units: dict[int, int]
    checked: tuple[bool, ...] | bool
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TileReport:
    """What :func:`apply_tiles` changed."""

    plates: int = 0
    """Plates swapped for a tile of the same size (part count unchanged)."""
    split_plates: int = 0
    """Plates without a tile of their size, covered by two or more tiles."""
    lowered: int = 0
    """Bricks rebuilt as a plate plus tiles: the face is a plate below the
    voxel top, so the smooth top lands where the model has it."""
    bricks: int = 0
    """Bricks rebuilt as two plates plus tiles (the face at the voxel top)."""
    topped: int = 0
    """Bricks and plates that keep their place and get tiles on top: the face
    is a plate above the voxel top."""
    added: int = 0
    """Parts added by splits and rebuilds."""
    kept: int = 0
    """Flat, open tops that keep their studs: no fitting tile (or plate) in the
    part's colour, or a split tile would rest on nothing."""
    unchecked: int = 0
    """Flat, open tops that keep their studs because their tiles would make the
    part heavier and there was no time left to check stability again."""
    heavier: bool = False
    """Some part became heavier (two plates plus a tile weigh more than the
    brick, an added tile weighs something): stability must be checked again."""
    faces: int = 0
    """Flat faces that got their tiles."""
    faces_kept: int = 0
    """Flat faces that keep all their studs: less than ``min_share`` of their
    open top could get tiles (issue #44)."""
    min_share: float = 0.0

    @property
    def tiled(self) -> int:
        """Parts that got a smooth top."""
        changed = (self.plates, self.split_plates, self.lowered, self.bricks)
        return sum(changed) + self.topped

    def summary(self) -> str:
        """One line for the user."""
        kinds = (
            (self.plates, "plate(s) -> tile"),
            (self.split_plates, "plate(s) -> 2+ tiles"),
            (self.lowered, "brick(s) -> plate + tile (top one plate lower)"),
            (self.bricks, "brick(s) -> 2 plates + tile"),
            (self.topped, "part(s) with a tile on top (top one plate higher)"),
        )
        done = [f"{count} {what}" for count, what in kinds if count] or ["none"]
        text = "tiles on flat tops: " + ", ".join(done)
        if self.added:
            text += f" (+{self.added} parts)"
        if self.kept:
            text += f"; {self.kept} flat top(s) cannot get tiles (no fitting tile)"
        if self.unchecked:
            text += (
                f"; {self.unchecked} flat top(s) keep their studs (no time to check "
                "stability with them; raise placement.time_limit_s)"
            )
        if self.faces_kept:
            text += (
                f"; {self.faces_kept} flat face(s) keep all their studs (less than "
                f"{self.min_share:.0%} of them could get tiles)"
            )
        return text


def apply_tiles(
    layout: Layout,
    flat: Mapping[Cell, float],
    *,
    allowed: frozenset[str] | None = None,
    produced: Callable[[str, int], bool | None] = produced_in,
    base: bool = True,
    heavier: bool = True,
    min_share: float = 0.0,
) -> TileReport:
    """Give the open bricks and plates whose top lies in ``flat`` a smooth top.

    ``flat`` maps plate cells to how far the flat face lies above them, in
    plates (:func:`~mesh2brick.place.tiles.flat_top_plates`). A part qualifies
    when every cell of its top layer is in it and nothing sits on it; its
    tiles go where the face is, rounded to a plate and at most one plate from
    the part's top:

    * face at the top: a plate becomes a tile of its size (several tiles when
      that size does not exist and each rests on something), a brick two
      plates of its size plus tiles;
    * one plate lower: a brick becomes a plate plus tiles (a plate stays at
      its height and becomes a tile);
    * one plate higher: tiles are laid on the part.

    Face by face (cells side by side in one layer, issue #44): a face gets its
    tiles only when the parts that can be smoothed cover at least
    ``min_share`` of its open top; otherwise all of it keeps its studs.

    Only parts in ``allowed`` (LDraw numbers, ``None``: any) that LEGO makes in
    the part's colour are used; ``base=False`` leaves the lowest brick layer
    alone; ``heavier=False`` makes only changes that do not add weight (they
    need no new stability check). Changes ``layout`` in place.
    """
    if not base:
        flat = {c: v for c, v in flat.items() if c[2] >= PLATES_PER_BRICK}
    tiles = _tile_sizes(layout.catalog, allowed)
    face_of = flat_faces(flat)
    open_cells: Counter[int] = Counter(
        face
        for (x, y, z), face in face_of.items()
        if layout.brick_at((x, y, z)) is not None
        and layout.brick_at((x, y, z + 1)) is None
    )
    plans: list[_TopPlan] = []
    for brick in list(layout):
        part = layout.part_of(brick)
        if part.category not in (Category.PLATE, Category.BRICK):
            continue
        if _rect_dims(part) is None:
            continue
        cells = layout.cells_of(brick)
        top = max(c[2] for c in cells)
        roof = [c for c in cells if c[2] == top]
        if any(c not in flat for c in roof) or any(
            layout.brick_at((x, y, top + 1)) is not None for x, y, _ in roof
        ):
            continue
        face = sum(flat[c] for c in roof) / len(roof)
        plans.append(
            _plan_top(
                layout,
                brick,
                roof=roof,
                rise=max(-1, min(1, round(face))),
                tiles=tiles,
                allowed=allowed,
                produced=produced,
                heavier=heavier,
            )
        )
    tileable: Counter[int] = Counter()
    for plan in plans:
        if plan.steps:
            tileable[face_of[plan.roof[0]]] += len(plan.roof)
    chosen = tiled_faces(open_cells, tileable, min_share)
    counts: Counter[str] = Counter()
    gained = False
    for plan in plans:
        if not plan.steps:
            counts[plan.kind] += 1
            continue
        if face_of[plan.roof[0]] not in chosen:
            continue
        outcome = _apply_top(layout, plan)
        counts[outcome.kind] += 1
        counts["added"] += outcome.added
        gained = gained or outcome.heavier
    return TileReport(
        plates=counts["plates"],
        split_plates=counts["split_plates"],
        lowered=counts["lowered"],
        bricks=counts["bricks"],
        topped=counts["topped"],
        added=counts["added"],
        kept=counts["kept"],
        unchecked=counts["unchecked"],
        heavier=gained,
        faces=len(chosen),
        faces_kept=len(open_cells) - len(chosen),
        min_share=min_share,
    )


def _tile_sizes(
    catalog: Catalog, allowed: frozenset[str] | None
) -> dict[tuple[int, int], tuple[str, str]]:
    """``(small, big)`` -> (part key, LDraw number) of every usable tile."""
    sizes: dict[tuple[int, int], tuple[str, str]] = {}
    for key, part in sorted(catalog.parts.items()):
        if part.category is not Category.TILE and not is_finishing_tile(part):
            continue
        dims = _rect_dims(part)
        if dims is None or (allowed is not None and part.ldraw_part not in allowed):
            continue
        sizes.setdefault((dims[0], dims[1]), (key, part.ldraw_part))
    return sizes


def _plate_like(
    layout: Layout,
    part: Any,
    colour: int,
    allowed: frozenset[str] | None,
    produced: Callable[[str, int], bool | None],
) -> str | None:
    """Key of the plate with ``part``'s footprint, if allowed and made in ``colour``."""
    width, length, _ = _rect_dims(part) or (0, 0, 0)
    plate = layout.catalog.rect_key(width, length, 1, category=Category.PLATE)
    if plate is None:
        return None
    number = layout.catalog[plate].ldraw_part
    if (allowed is not None and number not in allowed) or produced(
        number, colour
    ) is False:
        return None
    return str(plate)


@dataclass(frozen=True, slots=True)
class _Outcome:
    kind: str
    added: int = 0
    heavier: bool = False


@dataclass(frozen=True, slots=True)
class _TopPlan:
    """How one open part gets a smooth top (nothing changed yet).

    ``steps`` are the parts to place (key, cells, layer); empty when the part
    keeps its studs, with ``kind`` saying why (``kept`` or ``unchecked``).
    """

    brick: PlacedBrick
    roof: tuple[Cell, ...]
    kind: str
    steps: tuple[tuple[str, frozenset[Cell], int], ...] = ()
    keep: bool = False
    """The part stays and carries the tiles (face a plate higher)."""
    heavier: bool = False


def _plan_top(
    layout: Layout,
    brick: PlacedBrick,
    *,
    roof: list[Cell],
    rise: int,
    tiles: dict[tuple[int, int], tuple[str, str]],
    allowed: frozenset[str] | None,
    produced: Callable[[str, int], bool | None],
    heavier: bool = True,
) -> _TopPlan:
    """Plan a smooth top ``rise`` plates from the part's top (-1, 0, 1).

    Without ``heavier`` a change that adds weight is left out (``unchecked``).
    """
    colour = brick.colour_code
    part = layout.part_of(brick)
    is_plate = part.category is Category.PLATE
    rise = max(rise, 0) if is_plate else rise  # a plate cannot go lower
    xs = sorted({c[0] for c in roof})
    ys = sorted({c[1] for c in roof})
    axis = 0 if len(xs) >= len(ys) else 1
    along, across = (xs, ys) if axis == 0 else (ys, xs)
    usable = {
        size: key
        for size, (key, ldraw) in tiles.items()
        if produced(ldraw, colour) is not False
    }
    cover = tile_cover(len(along), len(across), usable.keys())
    kept = _TopPlan(brick, tuple(roof), "kept")
    if cover is None:
        return kept
    top = roof[0][2]
    tile_layer = top + rise

    def cells(piece_along: range, piece_across: range) -> frozenset[Cell]:
        return frozenset(
            (along[a], across[c], tile_layer)
            if axis == 0
            else (across[c], along[a], tile_layer)
            for a in piece_along
            for c in piece_across
        )

    steps: list[tuple[str, frozenset[Cell], int]] = [
        (
            usable[piece.footprint],
            cells(
                range(piece.along, piece.along + piece.length),
                range(piece.across, piece.across + piece.width),
            ),
            tile_layer,
        )
        for piece in cover
    ]
    keep = rise > 0
    if is_plate and not keep:
        if len(steps) > 1 and not all(
            any(layout.brick_at((x, y, top - 1)) is not None for x, y, _ in target)
            for _, target, _ in steps
        ):
            return kept
        kind = "plates" if len(steps) == 1 else "split_plates"
    elif keep:
        kind = "topped"
    else:
        plate = _plate_like(layout, part, colour, allowed, produced)
        if plate is None:
            return kept
        steps = [
            (plate, frozenset((x, y, z) for x, y, _ in roof), z)
            for z in range(brick.layer, tile_layer)
        ] + steps
        kind = "lowered" if rise < 0 else "bricks"
    before = 0.0 if keep else part.mass_g
    after = sum(layout.catalog[key].mass_g for key, _, _ in steps)
    gains = after > before + _MASS_EPS
    if gains and not heavier:
        return _TopPlan(brick, tuple(roof), "unchecked")
    return _TopPlan(brick, tuple(roof), kind, tuple(steps), keep, gains)


def _apply_top(layout: Layout, plan: _TopPlan) -> _Outcome:
    """Carry out :func:`_plan_top`'s plan (undone if a part does not fit)."""
    brick = plan.brick
    colour = brick.colour_code
    if not plan.keep:
        layout.remove(brick.brick_id)
    placed: list[int] = []
    for key, target, z in plan.steps:
        new = _place_exact(layout, key, target, z, colour)
        if new is None:
            layout.remove_many(placed)
            if not plan.keep:
                layout.add(
                    brick.part_key, brick.x, brick.y, brick.layer, brick.yaw, colour
                )
            return _Outcome("kept")
        placed.append(new)
    added = len(placed) - (0 if plan.keep else 1)
    return _Outcome(plan.kind, added=added, heavier=plan.heavier)


# ---------------------------------------------------------------- joint pattern
def stacked_joints(layout: Layout) -> tuple[int, int]:
    """(stacked, total): vertical joints at brick interfaces that continue up.

    A joint between two bricks ends at the interface to the layer above; it
    is *stacked* if the layer above has a joint at the same place (no brick
    bridges it), the weak pattern of a wall without bond.
    """
    occ = layout.occupancy
    total = stacked = 0
    for (x, y, z), brick in occ.items():
        below = (x, y, z - 1)
        if below not in occ or occ[below] == brick:
            continue
        for dx, dy in ((1, 0), (0, 1)):
            beside_below = (x + dx, y + dy, z - 1)
            if beside_below in occ and occ[beside_below] != occ[below]:
                total += 1
                beside = (x + dx, y + dy, z)
                if beside in occ and occ[beside] != brick:
                    stacked += 1
    return stacked, total


@contextmanager
def _placement_catalog(catalog: Catalog) -> Iterator[None]:
    """Let legolization's ``run()`` place from ``catalog`` (local patch).

    ``run()`` always takes ``default_catalog()`` and ``PipelineConfig`` has
    no catalogue option (docs/UPSTREAM.md #8). Every other legolization API
    used here receives the catalogue explicitly.
    """
    namespace = _lego_pipeline.__dict__
    original = namespace["default_catalog"]
    namespace["default_catalog"] = lambda: catalog  # documented local patch
    try:
        yield
    finally:
        namespace["default_catalog"] = original


# ---------------------------------------------------------------- hard time limit
STAGE_GAUGES: Final = {
    "pipeline.placed": "placed",
    "pipeline.restored": "restored",
    "pipeline.remerged": "remerged",
}
"""legolization's phase readings (``_phase_gauge``) kept as fallback states."""
STAGE_LABELS: Final = {
    "unchecked": "placement, before its stability check",
    "placed": "placement and repair",
    "restored": "refilling weak hollow parts",
    "remerged": "the final merge",
    "finished": "the finished run",
}


@dataclass(frozen=True, slots=True)
class RunState:
    """A layout legolization reached during its run (ADR 0015).

    ``stability`` is ``None`` for a layout whose stability check had not
    finished (``stage == "unchecked"``).
    """

    stage: str
    layout: Layout
    stability: StabilityResult | None
    loose_removed: tuple[str, ...] = ()
    """LDraw numbers of loose parts :func:`drop_loose_parts` took out."""


MAX_LOOSE_PARTS: Final = 3
"""Up to this many parts that nothing holds are removed after placement."""


def drop_loose_parts(
    state: RunState,
    config: PipelineConfig,
    before_check: Callable[[RunState], None] | None = None,
) -> RunState | None:
    """``state`` without the few parts not connected to the ground, re-checked.

    legolization sometimes leaves a single part that no stud connection
    reaches (Duo at 48 studs: one 1 x 1 brick under an overhang), which makes
    the whole model unbuildable. Up to :data:`MAX_LOOSE_PARTS` such parts are
    removed and the stability is checked again; more are kept (removing
    them would change the model visibly). ``before_check`` receives ``state``
    before the new stability check starts. Returns ``None`` if nothing changes.
    """
    if state.stability is None:
        return None
    loose = ConnectionGraph.from_layout(state.layout).floating_ids()
    if not loose or len(loose) > MAX_LOOSE_PARTS:
        return None
    layout = state.layout.copy()
    removed = tuple(sorted(layout.part_of(layout.bricks[i]).ldraw_part for i in loose))
    layout.remove_many(sorted(loose))
    if before_check is not None:
        before_check(state)
    return RunState(state.stage, layout, analyze(layout, config.solver), removed)


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """What :func:`run_placement` got from legolization."""

    states: tuple[RunState, ...]
    """Intermediate states in the order legolization reached them."""
    final: RunState | None
    """The finished run's result; ``None`` if the time limit stopped it."""


def state_rank(state: RunState) -> int:
    """2: checked and buildable, 1: checked, 0: stability not checked."""
    if state.stability is None:
        return 0
    return 2 if _report(state.layout, state.stability).buildable else 1


def choose_state(
    outcome: RunOutcome, rank: Callable[[RunState], int] = state_rank
) -> tuple[RunState, list[str]]:
    """The best state of a run: highest :func:`state_rank`, the latest on ties.

    A finished run keeps its result unless only an earlier state is
    buildable. Returns the state and notes for the user.

    Raises:
        BackendError: if the time limit stopped the run before any layout.
    """
    candidates = [*outcome.states, *(() if outcome.final is None else (outcome.final,))]
    if not candidates:
        msg = (
            "the time limit was reached before legolization placed a first model; "
            "raise placement.time_limit_s or make the model smaller (e.g. --size)"
        )
        raise BackendError(msg)
    ranks = [rank(state) for state in candidates]
    best = max(range(len(candidates)), key=lambda i: (ranks[i], i))
    state = candidates[best]
    label = STAGE_LABELS.get(state.stage, state.stage)
    if outcome.final is None:
        kind = {2: "best stable", 1: "best (not stable)", 0: "only"}[ranks[best]]
        note = (
            f"time limit reached: legolization was stopped; using the {kind} model "
            f"found so far, after {label} ({len(state.layout)} parts). Raise "
            "placement.time_limit_s for the full optimisation (usually fewer parts)"
        )
        return state, [note]
    if state is outcome.final:
        return state, []
    note = (
        "legolization's last passes left the model unstable; using the stable "
        f"model after {label} ({len(state.layout)} parts)"
    )
    return state, [note]


@contextmanager
def _state_hook(on_state: Callable[[RunState], None]) -> Iterator[None]:
    """Report every layout legolization's ``run()`` reaches (local patch).

    ``run()`` has no callback for its intermediate results; it calls
    ``_phase_gauge(name, layout, stability)`` after placement, every
    refill round and the final merge, and ``analyze`` (module global)
    before every stability check. Both are wrapped for the duration of
    ``run()`` (docs/UPSTREAM.md #5).
    """
    namespace = _lego_pipeline.__dict__
    gauge, check = namespace["_phase_gauge"], namespace["analyze"]

    def phase_gauge(name: str, layout: Layout, stability: StabilityResult) -> None:
        gauge(name, layout, stability)
        if name in STAGE_GAUGES:
            on_state(RunState(STAGE_GAUGES[name], layout, stability))

    def analyze_hook(layout: Layout, *args: Any, **kwargs: Any) -> StabilityResult:
        on_state(RunState("unchecked", layout, None))
        result: StabilityResult = check(layout, *args, **kwargs)
        return result

    namespace["_phase_gauge"] = phase_gauge  # documented local patch
    namespace["analyze"] = analyze_hook
    try:
        yield
    finally:
        namespace["_phase_gauge"], namespace["analyze"] = gauge, check


def _check_state_hook() -> None:
    """Fail early if legolization no longer has what :func:`_state_hook` wraps."""
    namespace = _lego_pipeline.__dict__
    if not all(callable(namespace.get(n)) for n in ("_phase_gauge", "analyze")):
        msg = (
            f"legolization {VERSION}: pipeline._phase_gauge/analyze changed; "
            "revisit the local patch in backends/legolization.py"
        )
        raise BackendError(msg)


_check_state_hook()


def run_placement(
    grid: LegoGrid,
    config: PipelineConfig,
    parts: frozenset[str],
    *,
    stop_at: Callable[[int], float] | None = None,
    progress: Callable[[str], None] | None = None,
) -> RunOutcome:
    """Run legolization's pipeline, stopped at ``stop_at`` (ADR 0015).

    ``stop_at(parts)`` gives the :func:`time.monotonic` time to stop, given
    the part count of the latest state (0 before the first). With a stop
    time the run happens in a child process that reports its states and is
    terminated when the time is up; without one it runs in this process.
    ``parts`` are the placeable LDraw parts (the whitelist).

    Raises:
        BackendError: if legolization rejects the input or fails.
    """
    if stop_at is None:
        states: list[RunState] = []

        def keep(state: RunState) -> None:
            states.append(dataclasses.replace(state, layout=state.layout.copy()))

        try:
            with _placement_catalog(restricted_catalog(parts)), _state_hook(keep):
                result = run(grid, config)
        except ValueError as error:
            raise BackendError(f"legolization rejected the input: {error}") from error
        final = RunState("finished", result.layout, result.stability)
        final = drop_loose_parts(final, config, states.append) or final
        return RunOutcome(states=tuple(states), final=final)
    return _run_in_child(grid, config, parts, stop_at, progress)


def _run_in_child(
    grid: LegoGrid,
    config: PipelineConfig,
    parts: frozenset[str],
    stop_at: Callable[[int], float],
    progress: Callable[[str], None] | None,
) -> RunOutcome:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(
        target=_run_worker,
        args=(grid, dataclasses.replace(config, progress=None), parts, sender),
        kwargs={"report_progress": progress is not None},
        daemon=True,
    )
    worker.start()
    sender.close()
    states: list[RunState] = []
    try:
        while True:
            known = len(states[-1].layout) if states else 0
            wait = stop_at(known) - time.monotonic()
            if wait <= 0 or not receiver.poll(wait):
                if progress is not None:
                    progress("time limit reached: stopping legolization")
                return RunOutcome(states=tuple(states), final=None)
            kind, payload = receiver.recv()
            if kind == "progress" and progress is not None:
                progress(payload)
            elif kind == "state":
                states.append(payload)
            elif kind == "done":
                return RunOutcome(states=tuple(states), final=payload)
            elif kind == "rejected":
                msg = f"legolization rejected the input: {payload}"
                raise BackendError(msg)
            elif kind == "error":
                raise BackendError(f"placement failed: {payload}") from payload
    except EOFError as error:
        msg = "the placement process ended without a result"
        raise BackendError(msg) from error
    finally:
        receiver.close()
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=10)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=10)


def _run_worker(
    grid: LegoGrid,
    config: PipelineConfig,
    parts: frozenset[str],
    sender: Connection,
    *,
    report_progress: bool,
) -> None:
    """Child-process entry point: run and send states, progress and result."""

    def send(kind: str, payload: object) -> None:
        sender.send((kind, payload))

    if report_progress:
        config = dataclasses.replace(config, progress=lambda m: send("progress", m))
    try:
        with (
            _placement_catalog(restricted_catalog(parts)),
            _state_hook(lambda state: send("state", state)),
        ):
            result = run(grid, config)
        final = RunState("finished", result.layout, result.stability)
        # The unchanged result is sent first; it counts if the limit stops
        # the new stability check.
        final = drop_loose_parts(final, config, lambda s: send("state", s)) or final
        send("done", final)
    except ValueError as error:
        send("rejected", str(error))
    except Exception as error:  # reported to the parent
        send("error", error)
    finally:
        sender.close()


@dataclass(frozen=True, slots=True)
class _Native:
    """What we keep of legolization's result to export without a round trip."""

    layout: Layout
    plan: InstructionPlan | None
    checked: tuple[bool, ...] | bool = True
    """Per step of ``plan`` whether its verdict was checked (``True``: all)."""
    units: Mapping[int, int] = dataclasses.field(default_factory=dict)
    """Brick id -> pre-assembly unit number within its step."""


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
        availability = settings.parts.availability
        early: list[str] = []
        if availability == "exclude":
            gone = unavailable_parts(grid.colors_used, settings)
            if gone:
                parts = settings.parts.model_copy(
                    update={"exclude": tuple(sorted({*settings.parts.exclude, *gone}))}
                )
                settings = settings.model_copy(update={"parts": parts})
                early.append(
                    f"left out {len(gone)} part(s) LEGO does not make in all colours "
                    f"of this model: {', '.join(sorted(gone))} (parts.availability)"
                )
        allowed = whitelist(settings)
        config = self.pipeline_config(
            settings, height_unit=grid.height_unit, allowed=allowed
        )
        outcome = run_placement(
            to_lego_grid(grid),
            config,
            allowed.parts,
            stop_at=(
                None
                if deadline is None
                else lambda parts: deadline - export_reserve_s(parts)
            ),
            progress=self._progress,
        )
        state, chosen = choose_state(outcome)
        early.extend(chosen)
        if state.loose_removed:
            early.append(
                f"removed {len(state.loose_removed)} loose part(s) that nothing holds "
                f"({', '.join(state.loose_removed)}); stability checked again"
            )
        layout = state.layout
        resolve_ignore_colours(layout)  # states before the final merge have them
        stability = _report(layout, state.stability)
        tiling = self._tile_tops(
            layout,
            grid,
            settings=settings,
            config=config,
            allowed=allowed,
            stability=stability,
            deadline=deadline,
        )
        early.extend(tiling.notes)
        if availability == "split":
            report = split_unavailable(layout)
            if report.replaced and stability.checked:
                stability = _report(layout, analyze(layout, config.solver))
            if report.replaced:
                early.append(
                    f"replaced {report.replaced} part(s) LEGO does not make in their "
                    f"colour by {report.added} shorter one(s) "
                    "(parts.availability=split)"
                )
            if report.unresolved:
                early.append(
                    f"{len(report.unresolved)} part(s) could not be replaced by "
                    "existing shorter parts; see the parts list"
                )
        steps = self._steps(layout, config, settings, deadline)
        if tiling.check is not None and tiling.before is not None:
            tiled = tiling.check.result()
            if stability.buildable and not tiled.buildable:
                layout.replace_with(tiling.before)
                early = [n for n in early if n not in tiling.notes]
                early.append(_TILES_UNDONE_NOTE)
                steps = self._steps(layout, config, settings, deadline)
            else:
                stability = tiled
        plan, units, checked = steps.plan, steps.units, steps.checked
        notes = [*allowed.notes, *early, *steps.notes]
        native = _Native(layout=layout, plan=plan, checked=checked, units=units)
        return Placement(
            model=to_brick_model(
                layout,
                plan,
                name=name,
                source=(
                    f"{NAME} {VERSION}, strategy {config.strategy}, seed {config.seed}"
                ),
                checked=checked,
                units=units,
                buildable=stability.buildable if stability.checked else None,
                best_so_far=outcome.final is None,
            ),
            stability=stability,
            backend=NAME,
            native=native,
            notes=tuple(notes),
        )

    def _tile_tops(
        self,
        layout: Layout,
        grid: VoxelGrid,
        *,
        settings: Settings,
        config: PipelineConfig,
        allowed: Whitelist,
        stability: StabilityReport,
        deadline: float | None,
    ) -> _Tiling:
        """Tiles on the flat tops (ROADMAP 9, ADR 0020).

        When a part got heavier, the whole model is checked again in a thread
        while the steps are planned (the step planner waits on its own worker
        processes); :meth:`place` undoes the tiles if the model no longer
        holds together. With too little time left for that check only the
        changes that make parts lighter are made; none when the run's own
        stability check did not finish.
        """
        parts = settings.parts
        if "tile" not in parts.categories:
            return _Tiling()
        if not stability.checked:
            return _Tiling(notes=(_TILES_UNCHECKED_NOTE,))
        left = (
            math.inf
            if deadline is None
            else deadline - time.monotonic() - export_reserve_s(len(layout))
        )
        before = layout.copy()
        report = apply_tiles(
            layout,
            flat_top_plates(_tile_faces(grid, parts.tiles), grid.plates_per_cell),
            allowed=allowed.parts,
            base=parts.tiles_on_base,
            heavier=left >= tile_check_s(len(layout)),
            min_share=parts.tiles_min_share,
        )
        shown = report.tiled or report.kept or report.unchecked or report.faces_kept
        notes = (report.summary(),) if shown else ()
        if not report.tiled or not report.heavier:
            # Nothing changed, or only lighter parts on the same supports: the
            # verdict stands (ADR 0020).
            return _Tiling(notes=notes)
        self._say(f"{report.summary()}; checking stability again")
        snapshot = layout.copy()
        solver = config.solver
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tile-check")
        check = pool.submit(lambda: _report(snapshot, analyze(snapshot, solver)))
        pool.shutdown(wait=False)
        return _Tiling(notes=notes, before=before, check=check)

    def _steps(
        self,
        layout: Layout,
        config: PipelineConfig,
        settings: Settings,
        deadline: float | None,
    ) -> _Steps:
        """Plan the steps and check them as far as time allows (ADR 0017)."""
        plan, notes, kind = self._plan(layout, config, settings, deadline)
        plan, units, refined = refine_plan(
            layout, plan, settings.steps, checked=kind == "searched"
        )
        checked: tuple[bool, ...] | bool = kind == "searched"
        if kind == "checked-layers":
            reserve = LLM_RESERVE_S if settings.llm.enabled else 0.0
            plan, checked, check_notes = self._check_steps(
                layout, plan, config, None if deadline is None else deadline - reserve
            )
            refined.extend(check_notes)
        return _Steps(plan, units, checked, (*notes, *refined))

    def _plan(
        self,
        layout: Layout,
        config: PipelineConfig,
        settings: Settings,
        deadline: float | None,
    ) -> tuple[InstructionPlan, list[str], str]:
        """Choose and run the step planner within the remaining time (ADR 0017).

        Returns the plan, notes for the user and its kind: ``searched``
        (legolization's search, checked step by step), ``checked-layers``
        (layer order, to be checked by :meth:`_check_steps`) or ``layers``
        (layer order without checks).
        """
        budget = None
        if deadline is not None:
            budget = deadline - time.monotonic() - export_reserve_s(len(layout))
        choice = choose_planner(settings.steps.sequencing, len(layout), budget)
        notes: list[str] = []
        if choice.planner in ("thorough", "fast"):
            smart = dataclasses.replace(
                config.instructions, mode="smart", solver=config.solver
            )
            limit = choice.search_s
            self._say(
                "planning stability-checked steps"
                + (f" (up to {limit:.0f} s)" if limit is not None else "")
            )
            plan = plan_with_timeout(layout, smart, limit)
            if plan is not None:
                return plan, notes, "searched"
            notes.append(_SEARCH_FALLBACK_NOTE)
            return layer_plan(layout, config.instructions), notes, "checked-layers"
        if choice.planner == "layers" and choice.reason == "no time left":
            notes.append(_TIME_FALLBACK_NOTE)
        return layer_plan(layout, config.instructions), notes, choice.planner

    def _check_steps(
        self,
        layout: Layout,
        plan: InstructionPlan,
        config: PipelineConfig,
        deadline: float | None,
    ) -> tuple[InstructionPlan, tuple[bool, ...], list[str]]:
        """Check the state after every step of a layer plan, in parallel.

        Returns the plan with real verdicts, which steps got one and notes.
        Steps the time limit leaves unchecked keep no verdict.
        """
        count = len(plan.steps)
        left = None
        if deadline is not None:
            left = deadline - time.monotonic() - export_reserve_s(len(layout))
            if left < MIN_SEQUENCING_S:
                return plan, (False,) * count, [_TIME_FALLBACK_NOTE]
        workers = default_workers()
        self._say(
            f"checking {count} intermediate states for stability with {workers} "
            "processes" + (f" (up to {left:.0f} s)" if left is not None else "")
        )
        verdicts = check_states(
            layout,
            [step.brick_ids for step in plan.steps],
            config.solver,
            deadline=None if left is None else time.monotonic() + left,
            workers=workers,
        )
        steps = tuple(
            step
            if verdict is None
            else dataclasses.replace(
                step, prefix_stable=verdict.stable, prefix_max_score=verdict.score
            )
            for step, verdict in zip(plan.steps, verdicts, strict=True)
        )
        mask = tuple(verdict is not None for verdict in verdicts)
        return (
            dataclasses.replace(plan, steps=steps),
            mask,
            _check_notes(len(layout), steps, mask),
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
            config=replace(config.instructions, mode="smart", solver=config.solver),
        )
        plan, units, _ = refine_plan(native.layout, plan, settings.steps, checked=True)
        return replace(
            placement,
            model=to_brick_model(
                native.layout,
                plan,
                name=placement.model.name,
                source=placement.model.source,
                units=units,
                buildable=placement.stability.buildable,
            ),
            native=_Native(layout=native.layout, plan=plan, units=units),
        )

    def merge_steps(
        self, placement: Placement, ranges: Sequence[tuple[int, int]]
    ) -> Placement:
        """Build each run of consecutive steps in ``ranges`` as one step.

        ``ranges`` are 0-based, inclusive and checked by the caller with
        :func:`mesh2brick.steps.regroup.merge_problems`. The LDraw export and
        the model both follow the merged plan; verdicts carry over.

        Raises:
            BackendError: for invalid ranges or a placement without a plan.
        """
        native = _native_of(placement)
        if native.plan is None:
            msg = "this placement has no step plan to merge"
            raise BackendError(msg)
        if not ranges:
            return placement
        steps = _plan_steps(native.plan, native.units)
        try:
            merged = merge_ranges(steps, ranges)
        except ValueError as error:
            raise BackendError(f"cannot merge steps: {error}") from error
        plan = _rebuild_plan(native.layout, native.plan, merged)
        units = _unit_numbers(merged)
        checked = native.checked
        if not isinstance(checked, bool):
            checked = tuple(all(checked[i] for i in step.origin) for step in merged)
        model = to_brick_model(
            native.layout,
            plan,
            name=placement.model.name,
            source=placement.model.source,
            checked=checked,
            units=units,
            buildable=placement.model.buildable,
        )
        return replace(
            placement,
            model=model,
            native=dataclasses.replace(native, plan=plan, units=units, checked=checked),
        )

    # ------------------------------------------------------------ Exporter
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
        allowed: Whitelist | None = None,
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
                "the legolization backend always needs bricks and plates; keep "
                "both in parts.categories (narrow them with parts.include/exclude)"
            )
            raise BackendError(msg)
        if allowed is not None:
            categories = set(allowed.categories(placeable_parts()))
        steps = settings.steps
        instructions = InstructionsConfig(
            # legolization's pipeline never sequences; place() plans the steps
            # itself so their cost can be bounded (see _plan).
            mode="layer",
            target_step_size=steps.parts_per_step,
            max_step_size=largest_step(steps.parts_per_step),
            min_step_size=min(STEP_SPREAD, steps.parts_per_step),
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
            # mesh2brick puts tiles on itself, only on flat tops (_tile_tops);
            # legolization's own pass would tile every exposed plate.
            "tiles": False,
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


def _tile_faces(grid: VoxelGrid, where: str) -> NDArray[np.float32]:
    """Flat faces of ``grid`` (``all``: every open top, at the cells' height)."""
    faces = grid.flat_tops()
    if where != "all":
        return faces
    open_tops = np.where(top_cells(grid.occupancy), 0.0, np.nan)
    every: NDArray[np.float32] = np.where(np.isfinite(faces), faces, open_tops).astype(
        np.float32
    )
    return every


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


def _check_notes(
    parts: int, steps: Sequence[LegoStep], checked: Sequence[bool]
) -> list[str]:
    """What the step checks of a layer plan found, for the user."""
    done = sum(checked)
    hands = sum(
        1
        for step, ok in zip(steps, checked, strict=True)
        if ok and not step.prefix_stable
    )
    held = (
        f"; {hands} of them need a supporting hand" if hands else "; every one stands"
    )
    if not done:
        return [_TIME_FALLBACK_NOTE]
    if done == len(steps):
        note = (
            f"{parts:,} parts: steps follow layer order (parts under overhangs are "
            f"pre-assembled); all {done} intermediate states were checked for "
            f"stability{held}"
        )
    else:
        note = (
            f"time limit reached while checking steps: {done} of {len(steps)} "
            f"intermediate states were checked for stability{held}; the others "
            "were not (raise placement.time_limit_s, e.g. --time 20min, to check "
            "all)"
        )
    return [note]


_STEP_NUMBERED: Final = re.compile(r"^(subassembly \S+: )?step \d+")


def refine_plan(
    layout: Layout,
    plan: InstructionPlan,
    steps: StepsConfig,
    *,
    checked: bool,
) -> tuple[InstructionPlan, dict[int, int], list[str]]:
    """Run mesh2brick's own step passes on a legolization plan (ADR 0012).

    Unchecked (layer-order) plans first get their hanging parts moved to the
    step of their holder; every plan then gets steps that are too small
    merged into a neighbour. Returns the new plan, the brick id -> unit
    number map of pre-assemblies and notes for the user.
    """
    structure = Structure.from_cells(
        {brick.brick_id: layout.cells_of(brick) for brick in layout},
        {brick.brick_id: str(layout.part_of(brick).category.value) for brick in layout},
    )
    rewritten = tuple(
        PlanStep(
            parts=step.brick_ids,
            submodel=step.submodel,
            attaches=step.attaches,
            origin=(index,),
        )
        for index, step in enumerate(plan.steps)
    )
    notes: list[str] = []
    target = steps.parts_per_step
    largest = largest_step(target)
    if not checked:
        hanging = attach_hanging(rewritten, structure)
        rewritten = split_large_steps(
            hanging.steps, structure, target=target, max_size=largest
        )
        if hanging.moved:
            notes.append(
                f"{hanging.moved} part(s) below an overhang are placed together "
                f"with the part that holds them ({hanging.units} pre-assemblies)"
            )
        if hanging.blocked:
            notes.append(
                f"{hanging.blocked} pre-assemblies cannot be lowered in from above "
                "and have to be pushed on from below"
            )
        if hanging.loose:
            notes.append(f"{hanging.loose} part(s) never get held by another part")
    rewritten = merge_small_steps(
        rewritten, structure, min_size=(target + 1) // 2, max_size=largest
    )
    return _rebuild_plan(layout, plan, rewritten), _unit_numbers(rewritten), notes


def _unit_numbers(steps: Sequence[PlanStep]) -> dict[int, int]:
    """Brick id -> pre-assembly unit number (1, 2, ... within its step)."""
    return {
        part: number
        for step in steps
        for number, group in enumerate(step.units, start=1)
        for part in group
    }


def _plan_steps(
    plan: InstructionPlan, units: Mapping[int, int]
) -> tuple[PlanStep, ...]:
    """A legolization plan as :class:`PlanStep` tuples, units included."""
    result = []
    for index, step in enumerate(plan.steps):
        groups: dict[int, list[int]] = {}
        for brick_id in step.brick_ids:
            if brick_id in units:
                groups.setdefault(units[brick_id], []).append(brick_id)
        result.append(
            PlanStep(
                parts=step.brick_ids,
                submodel=step.submodel,
                attaches=step.attaches,
                origin=(index,),
                units=tuple(tuple(groups[n]) for n in sorted(groups)),
            )
        )
    return tuple(result)


def _rebuild_plan(
    layout: Layout, plan: InstructionPlan, steps: Sequence[PlanStep]
) -> InstructionPlan:
    """Rebuild a legolization plan from rewritten steps, keeping their verdicts."""
    rebuilt = []
    for index, step in enumerate(steps, start=1):
        origins = [plan.steps[i] for i in step.origin]
        rotations = [o.rotstep for o in origins if o.rotstep is not None]
        rotstep = rotations[0] if rotations else None
        if rotations and all(r.mode == "REL" for r in rotations):
            yaw = sum(r.yaw for r in rotations) % 360
            rotstep = RotStep(yaw=yaw, mode="REL") if yaw else None
        rebuilt.append(
            LegoStep(
                index=index,
                brick_ids=step.parts,
                prefix_stable=all(o.prefix_stable for o in origins),
                prefix_max_score=max(o.prefix_max_score for o in origins),
                rotstep=rotstep,
                submodel=step.submodel,
                attaches=step.attaches,
                insertion_fragile=any(o.insertion_fragile for o in origins),
            )
        )
    result = InstructionPlan(
        steps=tuple(rebuilt),
        warnings=tuple(w for w in plan.warnings if not _STEP_NUMBERED.match(w)),
        bom=plan.bom,
        subassemblies=plan.subassemblies,
    )
    return dataclasses.replace(result, bom=bill_of_materials(layout, plan=result))


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
    checked: bool | Sequence[bool] = True,
    units: Mapping[int, int] | None = None,
    buildable: bool | None = None,
    best_so_far: bool = False,
) -> BrickModel:
    """Convert legolization's layout + plan into a :class:`BrickModel`.

    ``checked`` says whether the plan's per-step stability verdicts are real
    (all, none, or per step; unchecked layer-order steps carry placeholders);
    ``units`` maps brick ids to
    their pre-assembly unit within the step; ``best_so_far`` marks a layout
    the time limit cut short (ADR 0015).
    """
    step_of: dict[int, int] = {}
    steps: tuple[BuildStep, ...] = ()
    if plan is not None:
        for index, step in enumerate(plan.steps):
            for brick_id in step.brick_ids:
                step_of.setdefault(brick_id, index)
        real = (
            (checked,) * len(plan.steps)
            if isinstance(checked, bool)
            else tuple(checked)
        )
        steps = tuple(
            BuildStep(
                submodel=step.submodel,
                attaches=step.attaches,
                stable=step.prefix_stable if ok else None,
                fragile=ok and step.insertion_fragile,
            )
            for step, ok in zip(plan.steps, real, strict=True)
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
                category=part_category(part),
                backend_key=brick.part_key,
                unit=(units or {}).get(brick.brick_id),
                studs=_stud_columns(layout, brick),
            )
        )
    return BrickModel(
        name=name,
        parts=tuple(parts),
        steps=steps,
        colors=dict(sorted(colors.items())),
        source=source,
        mass_g=round(float(layout.total_mass_g()), 1),
        buildable=buildable,
        best_so_far=best_so_far,
    )


# ---------------------------------------------------------------- helpers
def _stud_columns(
    layout: Layout, brick: PlacedBrick
) -> tuple[tuple[int, int], ...] | None:
    """``(x, y)`` columns with a top stud, for slopes (the high row) only."""
    if layout.part_of(brick).category.value != "slope":
        return None
    return tuple(
        sorted({(c.cell[0], c.cell[1]) for c in layout.connectors_of(brick, top=True)})
    )


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


def _report(layout: Layout, stability: StabilityResult | None) -> StabilityReport:
    """Stability report; ``stability=None`` means the check did not finish."""
    graph = ConnectionGraph.from_layout(layout)
    if stability is None:
        return StabilityReport(
            stable=False,
            component_count=graph.component_count(),
            floating_count=len(graph.floating_ids()),
            max_score=math.nan,
            checked=False,
        )
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
