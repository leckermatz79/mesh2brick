# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Run configuration: pydantic schema, YAML loader and ``key=value`` overrides.

The schema mirrors ``mesh2brick.yaml`` (SPEC §4). Every field can be overridden
from the command line with ``--set section.field=value``; values are parsed as
YAML scalars/flow collections, so ``--set parts.categories=[brick,plate]`` and
``--set stability.enabled=false`` work as expected.

Backend-specific knobs are not duplicated here: they go into
``placement.backend_options`` and are validated by the selected backend.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from mesh2brick.voxel.grid import HeightUnit

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

Axis = Literal["x", "y", "z", "-x", "-y", "-z"]
PartCategory = Literal["brick", "plate", "slope", "tile"]
ColorMode = Literal["single", "height_bands", "cad", "vertex", "texture", "auto"]
OutputFormat = Literal[
    "ldr", "mpd", "bom_csv", "bom_bricklink", "bom_rebrickable", "pdf", "png"
]
LlmTask = Literal["group_steps", "write_step_text", "choose_part"]

DEFAULT_LLM_MODEL = "claude-sonnet-5-5"
MAX_HEIGHT_CM: Final = 400.0
"""Upper bound for ``input.target_height_cm`` (about as tall as 512 studs)."""
_SIZE: Final = re.compile(r"(\d+(?:[.,]\d+)?)\s*(cm|mm|studs?)", re.IGNORECASE)
_TIME: Final = re.compile(r"(\d+(?:[.,]\d+)?)\s*(s|min|h)", re.IGNORECASE)
_SECONDS_PER: Final = {"s": 1, "min": 60, "h": 3600}


class ConfigError(ValueError):
    """Raised when a configuration file or override is invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InputConfig(_Section):
    """How the input model is oriented and scaled."""

    up_axis: Axis = "z"
    auto_orient: bool = False
    scale_mode: Literal["studs", "mm"] = "studs"
    """``studs``: scale the model to a target size, ``target_height_cm`` if
    set, else ``target_studs``. ``mm``: keep the file's size (``mm_per_stud``)."""
    target_studs: Annotated[int, Field(gt=0, le=512)] = 32
    """Length of the longest model axis in studs (``scale_mode: studs``).

    Default 32 (~26 cm) by product-owner decision of 2026-11-01; SPEC §4 had 48.
    """
    target_height_cm: Annotated[float, Field(gt=0, le=MAX_HEIGHT_CM)] | None = None
    """Height of the LEGO model in centimetres; replaces ``target_studs`` when
    set (Roadmap 1). The height is rounded to the nearest whole brick (or
    plate), so 30 cm become 31 bricks = 29.8 cm. A size in cm means the height
    by product-owner decision of 2026-11-07; the longest edge stays reachable
    through ``target_studs``."""
    mm_per_stud: Annotated[float, Field(gt=0)] = 8.0
    """Model millimetres per stud (``scale_mode: mm``); a real stud pitch is 8 mm."""
    multi_body: Literal["union", "error"] = "union"
    """Files with several bodies/parts: ``union`` merges them into one solid
    (overlaps are unioned), ``error`` rejects such files."""
    step_tolerance_mm: Annotated[float, Field(gt=0)] = 0.05
    """Largest distance between a STEP surface and its triangles (mm)."""

    @model_validator(mode="after")
    def _check_scale(self) -> Self:
        if self.scale_mode == "mm" and self.target_height_cm is not None:
            msg = (
                "target_height_cm needs scale_mode: studs "
                "(scale_mode: mm keeps the size of the file)"
            )
            raise ValueError(msg)
        return self


class VoxelConfig(_Section):
    """Voxelization of the normalised mesh."""

    height_unit: HeightUnit = "brick"
    fill: Literal["solid", "hollow"] = "hollow"
    wall_thickness: Annotated[int, Field(ge=1)] = 2
    """Shell thickness in voxels when ``fill: hollow``."""
    threshold: Annotated[float, Field(gt=0, le=1)] = 0.5
    """Minimum filled volume fraction for a voxel to become occupied."""
    min_island_fraction: Annotated[float, Field(ge=0, le=1)] = 0.05
    """Disconnected voxel islands smaller than this share of all cells are
    removed (a LEGO model must be one piece); 0 keeps every island."""


class ColorConfig(_Section):
    """How voxel colours are chosen (codes are LDraw colour codes)."""

    mode: ColorMode = "auto"
    """Where colours come from.

    * ``single``: every cell is ``single_color``.
    * ``height_bands``: horizontal bands in ``bands``, bottom to top.
    * ``cad``: part and material colours of the file (STEP colours, 3MF
      materials and slicer filaments, OBJ/glTF material colours).
    * ``vertex``: per-vertex or per-face colours, else as ``cad``.
    * ``texture``: image textures, else as ``vertex``.
    * ``auto``: the most detailed colours the file has (like ``texture``).

    Surfaces without colour information get ``single_color``.
    """
    single_color: Annotated[int, Field(ge=0)] = 4
    palette: Literal["common", "solid", "all"] = "common"
    """Colours that model colours are matched to (ADR 0008).

    * ``common``: colours LEGO currently makes in many parts (about 40; easy to buy).
    * ``solid``: every opaque colour with BrickLink and Rebrickable numbers.
    * ``all``: every opaque LDraw colour of the library, including rare ones.
    """
    bands: tuple[Annotated[int, Field(ge=0)], ...] = (1, 2, 14, 25, 4)
    """Colours for ``mode: height_bands``, bottom to top (default: Blue, Green,
    Yellow, Orange, Red)."""

    @model_validator(mode="after")
    def _check_bands(self) -> Self:
        if not self.bands:
            msg = "color.bands needs at least one colour"
            raise ValueError(msg)
        return self


def _part_numbers(value: object) -> object:
    """Accept YAML-numeric part numbers (``[3001, 3004]``) as strings."""
    if isinstance(value, list | tuple):
        return tuple(str(v) if isinstance(v, int) else v for v in value)
    return value


PartNumbers = Annotated[tuple[str, ...], BeforeValidator(_part_numbers)]


class PartsConfig(_Section):
    """Which parts placement may use."""

    categories: tuple[PartCategory, ...] = ("brick", "plate", "slope")
    """Part families placement may use. ``slope`` is on again since 1.3.0: the
    LP attempt order made it cheap (every fixture stable, at most 1.45x the
    time without slopes, docs/benchmarks.md); ``[brick, plate]`` turns it off."""
    include: PartNumbers = ()
    """LDraw part numbers to allow explicitly (whitelist, Phase 4)."""
    exclude: PartNumbers = ()
    """LDraw part numbers to forbid (blacklist, Phase 4)."""
    max_parts: Annotated[int, Field(gt=0)] = 5000
    availability: Literal["report", "split", "exclude"] = "exclude"
    """Parts LEGO does not make in a colour (Rebrickable data, ADR 0010):
    ``exclude`` (default, measured best on a real model) keeps such parts out
    of placement for the whole model, ``split`` replaces each by shorter parts
    of the same colour after placement and re-checks stability, ``report``
    only flags them in the parts list."""
    tiles: Literal["flat", "all"] = "flat"
    """Where tiles go when ``tile`` is in ``categories`` (ROADMAP 9, ADR 0020):
    ``flat`` only on open tops the input mesh renders flat (a box's top, a
    base, a flat detail), ``all`` on every open top, the stairs of rounded
    shapes included. Plates become tiles of the same size, bricks two plates
    plus tiles; stability is checked again."""
    tiles_on_base: bool = True
    """Tiles also on the lowest brick layer (a base plate, a courtyard)."""
    tiles_min_share: Annotated[float, Field(ge=0.0, le=1.0)] = 0.85
    """A flat face gets tiles only when at least this share of its open top
    can (product owner, 2026-11-11, issue #44); otherwise all of it keeps its
    studs instead of looking patchy (0 = tile whatever can be tiled)."""
    tiles_split: bool = True
    """Split parts that reach past the edge of a flat face (or under another
    part) at the edge first, so whole faces can be tiled (product owner,
    2026-11-11, issue #46): outside they keep their studs, inside they get
    plates and tiles; each cut stays held by a part above or below."""

    @model_validator(mode="after")
    def _check_lists(self) -> Self:
        if not self.categories:
            msg = "parts.categories must name at least one category"
            raise ValueError(msg)
        if len(set(self.categories)) != len(self.categories):
            msg = "parts.categories contains duplicates"
            raise ValueError(msg)
        if overlap := sorted(set(self.include) & set(self.exclude)):
            msg = f"parts listed in both include and exclude: {', '.join(overlap)}"
            raise ValueError(msg)
        return self


class PlacementConfig(_Section):
    """Brick placement backend and strategy."""

    backend: Literal["legolization"] = "legolization"
    strategy: str = "kollsker"
    """Passed through to the backend; valid names come from the backend itself.
    ``kollsker`` was clearly fastest on a real 1,000-part model at similar part
    counts (docs/benchmarks.md); SPEC §4 had ``luo``."""
    seed: Annotated[int, Field(ge=0)] = 0
    time_limit_s: Annotated[float, Field(gt=0)] = 300.0
    """Wall-clock limit for a whole conversion (ADR 0006, 0015). When it runs
    short, cheaper steps are chosen (layer-order instructions); when it is
    reached, the backend is stopped and the best stable model found so far is
    used, marked on the cover page. Time for the export is kept free."""
    backend_options: dict[str, Any] = Field(default_factory=dict)
    """Backend-specific options, validated by the backend (not duplicated here)."""


class StabilityConfig(_Section):
    """Structural stability check and repair."""

    enabled: bool = True
    max_repair_iterations: Annotated[int, Field(ge=0)] = 20


class StepsConfig(_Section):
    """Build-step sequencing."""

    parts_per_step: Annotated[int, Field(ge=1, le=50)] = 7
    keep_symmetry: bool = True
    submodels: bool = True
    sequencing: Literal["auto", "thorough", "fast", "checked-layers", "layers"] = "auto"
    """How build steps are ordered. ``thorough``: legolization searches an
    order whose every intermediate state is stable, with sub-assemblies (time
    grows with the square of the part count). ``fast``: the same with one
    candidate per step. ``checked-layers``: bottom-up layer chunks with parts
    under overhangs pre-assembled, every intermediate state checked for
    stability afterwards, in parallel (ADR 0017). ``layers``: the same layer
    order without checks (seconds, may need a supporting hand). ``auto``:
    ``thorough`` for models up to 500 parts when its estimated time fits the
    time left, ``checked-layers`` otherwise. The search falls back to
    ``checked-layers`` when it does not finish in time; the checks stop at
    ``placement.time_limit_s``, and the states checked by then keep their
    verdict."""


class LlmConfig(_Section):
    """Optional LLM layer (needs the ``llm`` extra and an API key, ADR 0013).

    Claude proposes, mesh2brick checks: merged steps, section titles, step
    texts and part choices are only used when they pass the same checks as
    the rest of the pipeline; anything else falls back to the result without
    the LLM layer.
    """

    enabled: bool = False
    model: str = DEFAULT_LLM_MODEL
    tasks: tuple[LlmTask, ...] = ("group_steps", "write_step_text")
    """``group_steps``: merge steps and name build sections;
    ``write_step_text``: a short sentence per step; ``choose_part``: pick
    replacements for parts LEGO does not make in their colour (only with
    ``parts.availability: report``)."""
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    """How thoroughly Claude thinks (more effort costs more tokens)."""
    max_cost_usd: Annotated[float, Field(gt=0)] = 1.0
    """Cost limit per run in US dollars; tasks stop when it is reached."""
    max_turns: Annotated[int, Field(ge=1, le=30)] = 8
    """Requests per task conversation (tool calls and one round of fixes)."""
    examples: Annotated[int, Field(ge=0, le=20)] = 6
    """Example lines per task from well-rated earlier runs (0: none)."""
    feedback: bool = True
    """Record runs in the local feedback store and learn from ratings."""


class OutputConfig(_Section):
    """What gets written where."""

    dir: Path = Path("./out")
    formats: tuple[OutputFormat, ...] = (
        "mpd",
        "bom_csv",
        "bom_bricklink",
        "bom_rebrickable",
        "pdf",
    )
    """What to write. ``mpd`` (default since Phase 6) keeps sub-assemblies as
    their own LDraw sub-models with their own steps; ``ldr`` writes one flat
    file (sub-assemblies become ordinary steps)."""
    language: Literal["de", "en"] = "de"
    """Language of the PDF instructions."""
    page_size: Literal["A4", "letter"] = "A4"
    steps_per_page: Annotated[int, Field(ge=1, le=4)] = 2
    """Build steps per PDF page (1-4; 4 are laid out 2 x 2)."""

    @model_validator(mode="after")
    def _check_formats(self) -> Self:
        if not self.formats:
            msg = "output.formats must name at least one format"
            raise ValueError(msg)
        if {"ldr", "mpd"} <= set(self.formats):
            msg = "output.formats: choose either 'ldr' or 'mpd', not both"
            raise ValueError(msg)
        return self


class Settings(_Section):
    """The complete, validated configuration of one run."""

    input: InputConfig = Field(default_factory=InputConfig)
    voxel: VoxelConfig = Field(default_factory=VoxelConfig)
    color: ColorConfig = Field(default_factory=ColorConfig)
    parts: PartsConfig = Field(default_factory=PartsConfig)
    placement: PlacementConfig = Field(default_factory=PlacementConfig)
    stability: StabilityConfig = Field(default_factory=StabilityConfig)
    steps: StepsConfig = Field(default_factory=StepsConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="after")
    def _check_combinations(self) -> Self:
        if self.llm.enabled and not self.llm.tasks:
            msg = "llm.enabled is true but llm.tasks is empty"
            raise ValueError(msg)
        if len(set(self.llm.tasks)) != len(self.llm.tasks):
            msg = "llm.tasks contains duplicates"
            raise ValueError(msg)
        return self


def parse_override(text: str) -> tuple[tuple[str, ...], Any]:
    """Split ``section.field=value`` into a key path and a YAML-parsed value.

    Raises:
        ConfigError: if the override is not of the form ``a.b=value``.
    """
    key, sep, raw = text.partition("=")
    path = tuple(part.strip() for part in key.split("."))
    if not sep or not all(path):
        msg = f"invalid override {text!r}; expected section.field=value"
        raise ConfigError(msg)
    try:
        value = yaml.safe_load(raw) if raw.strip() else ""
    except yaml.YAMLError as error:
        msg = f"invalid value in override {text!r}: {error}"
        raise ConfigError(msg) from error
    return path, value


def size_overrides(text: str) -> tuple[str, ...]:
    """Overrides for a model size such as ``30cm``, ``300mm`` or ``40studs``.

    Centimetres and millimetres set the height of the LEGO model
    (``input.target_height_cm``); studs set the longest axis
    (``input.target_studs``), as in 1.0. Either way the model is scaled to
    that size, also when the configuration file says ``scale_mode: mm``.

    Raises:
        ConfigError: if ``text`` is not a positive number with one of the units.
    """
    match = _SIZE.fullmatch(text.strip())
    if match is None:
        msg = (
            f"invalid size {text!r}; give a number with a unit, "
            "e.g. 30cm, 300mm or 40studs"
        )
        raise ConfigError(msg)
    number = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    if number <= 0:
        msg = f"invalid size {text!r}; the size must be greater than 0"
        raise ConfigError(msg)
    if unit.startswith("stud"):
        if not number.is_integer():
            msg = f"invalid size {text!r}; studs are counted in whole numbers"
            raise ConfigError(msg)
        return (
            "input.scale_mode=studs",
            f"input.target_studs={int(number)}",
            "input.target_height_cm=null",
        )
    height_cm = number / 10 if unit == "mm" else number
    return ("input.scale_mode=studs", f"input.target_height_cm={height_cm!r}")


def time_overrides(text: str) -> tuple[str, ...]:
    """Overrides for a time limit such as ``20min``, ``90s`` or ``1h``.

    Sets ``placement.time_limit_s``, the hard limit for a whole conversion
    (Roadmap 2, ADR 0015).

    Raises:
        ConfigError: if ``text`` is not a positive number with one of the units.
    """
    match = _TIME.fullmatch(text.strip())
    if match is None:
        msg = f"invalid time {text!r}; give a number with a unit, e.g. 20min, 90s or 1h"
        raise ConfigError(msg)
    seconds = (
        float(match.group(1).replace(",", ".")) * _SECONDS_PER[match.group(2).lower()]
    )
    if seconds <= 0:
        msg = f"invalid time {text!r}; the time must be greater than 0"
        raise ConfigError(msg)
    return (f"placement.time_limit_s={seconds!r}",)


def apply_overrides(
    data: Mapping[str, Any], overrides: Iterable[str]
) -> dict[str, Any]:
    """Return a deep copy of ``data`` with ``key=value`` overrides applied."""
    result: dict[str, Any] = _deep_copy(data)
    for text in overrides:
        path, value = parse_override(text)
        node = result
        for part in path[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                msg = f"override {text!r}: {part!r} is not a section"
                raise ConfigError(msg)
            node = child
        node[path[-1]] = value
    return result


def load_settings(
    path: Path | None = None,
    overrides: Iterable[str] = (),
) -> Settings:
    """Load settings from an optional YAML file plus CLI overrides.

    Raises:
        ConfigError: with a readable, per-field message if anything is invalid.
    """
    data: dict[str, Any] = {}
    if path is not None:
        data = read_yaml(path)
    data = apply_overrides(data, overrides)
    try:
        return Settings.model_validate(data)
    except ValidationError as error:
        source = str(path) if path is not None else "settings"
        raise ConfigError(format_validation_error(error, source=source)) from error


def read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping from ``path`` (an empty file is an empty mapping).

    Raises:
        ConfigError: if the file is missing, unreadable or not a mapping.
    """
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        msg = f"cannot read config file {path}: {error.strerror or error}"
        raise ConfigError(msg) from error
    except yaml.YAMLError as error:
        msg = f"config file {path} is not valid YAML: {error}"
        raise ConfigError(msg) from error
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"config file {path} must contain a mapping at the top level"
        raise ConfigError(msg)
    return loaded


def format_validation_error(error: ValidationError, *, source: str) -> str:
    """Render a pydantic error as one readable line per problem."""
    lines = [f"invalid configuration in {source}:"]
    for problem in error.errors():
        location = ".".join(str(part) for part in problem["loc"]) or "(top level)"
        message = problem["msg"].removeprefix("Value error, ")
        lines.append(f"  - {location}: {message}")
    return "\n".join(lines)


def settings_to_yaml(settings: Settings) -> str:
    """Serialise settings back to YAML (round-trips through :func:`load_settings`)."""
    data = settings.model_dump(mode="json")
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _deep_copy(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _deep_copy(value) if isinstance(value, dict) else value
        for key, value in data.items()
    }
