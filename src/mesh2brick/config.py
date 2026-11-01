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

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self

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
OutputFormat = Literal[
    "ldr", "mpd", "bom_csv", "bom_bricklink", "bom_rebrickable", "pdf", "png"
]
LlmTask = Literal["group_steps", "write_step_text", "choose_part"]

DEFAULT_LLM_MODEL = "claude-sonnet-5-5"


class ConfigError(ValueError):
    """Raised when a configuration file or override is invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InputConfig(_Section):
    """How the input model is oriented and scaled."""

    up_axis: Axis = "z"
    auto_orient: bool = False
    scale_mode: Literal["studs", "mm"] = "studs"
    target_studs: Annotated[int, Field(gt=0, le=512)] = 32
    """Length of the longest model axis in studs (``scale_mode: studs``).

    Default 32 (~26 cm) by product-owner decision of 2026-11-01; SPEC §4 had 48.
    """
    mm_per_stud: Annotated[float, Field(gt=0)] = 8.0
    """Model millimetres per stud (``scale_mode: mm``); a real stud pitch is 8 mm."""


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

    mode: Literal["single", "vertex", "texture", "cad", "height_bands"] = "single"
    single_color: Annotated[int, Field(ge=0)] = 4
    palette: Literal["solid", "all"] = "solid"
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

    categories: tuple[PartCategory, ...] = ("brick", "plate")
    """Part families placement may use. ``slope`` is opt-in for now: with
    legolization 0.5.0 it can slow placement down 50x (docs/UPSTREAM.md #2);
    SPEC §4 lists it as a default."""
    include: PartNumbers = ()
    """LDraw part numbers to allow explicitly (whitelist, Phase 4)."""
    exclude: PartNumbers = ()
    """LDraw part numbers to forbid (blacklist, Phase 4)."""
    max_parts: Annotated[int, Field(gt=0)] = 5000

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
    """Wall-clock budget for a whole conversion. When it runs short, cheaper
    steps are chosen (layer-order instructions) and the result says so."""
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
    sequencing: Literal["auto", "thorough", "fast", "layers"] = "auto"
    """How build steps are ordered. ``thorough``: every intermediate state is
    checked for stability, with a search when the order gets stuck (best
    instructions, slow for big models). ``fast``: one candidate per step and a
    cheap layer-order escape instead of the search. ``layers``: bottom-up layer
    chunks without stability checks (seconds, may need a supporting hand).
    ``auto``: ``thorough`` for models up to 500 parts, ``layers`` above. The
    checked modes fall back to ``layers`` when ``placement.time_limit_s`` runs
    out."""


class LlmConfig(_Section):
    """Optional LLM layer (needs the ``llm`` extra and an API key)."""

    enabled: bool = False
    model: str = DEFAULT_LLM_MODEL
    tasks: tuple[LlmTask, ...] = ("group_steps", "write_step_text")


class OutputConfig(_Section):
    """What gets written where."""

    dir: Path = Path("./out")
    formats: tuple[OutputFormat, ...] = (
        "ldr",
        "bom_csv",
        "bom_bricklink",
        "bom_rebrickable",
        "pdf",
    )
    language: Literal["de", "en"] = "de"
    page_size: Literal["A4", "letter"] = "A4"

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
