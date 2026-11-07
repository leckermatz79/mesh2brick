# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Backend-independent brick model: placed parts plus their build steps.

A :class:`BrickModel` is what every stage after placement works on (BOM,
rendering, PDF, LLM layer). It is produced by a placement backend, is
immutable, and serialises to JSON so each pipeline stage can run on its own.

Coordinates are grid coordinates, z-up: ``x``/``y`` in studs, ``layer`` in
plate heights (a brick spans 3 layers). They are *not* LDraw coordinates; the
LDraw transform lives in the backend.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from pathlib import Path

Cell = tuple[int, int, int]
SCHEMA_VERSION: Final = 3
"""Version 2 (Phase 6) added step verdicts, pre-assembly units, mass and the
buildability verdict; version 3 (Phase 7) added section titles and step
texts. Older files still load (the new fields default)."""
READABLE_SCHEMAS: Final = frozenset({1, 2, SCHEMA_VERSION})
MAX_SECTION_CHARS: Final = 40
MAX_STEP_TEXT_CHARS: Final = 200
MM_PER_STUD: Final = 8.0
MM_PER_PLATE: Final = 3.2
STUD_HEIGHT_MM: Final = 1.7


@dataclass(frozen=True, slots=True)
class ColorInfo:
    """Display data for one LDraw colour code."""

    name: str
    rgb_hex: str
    """``#rrggbb``"""


@dataclass(frozen=True, slots=True)
class PlacedPart:
    """One part instance in the model.

    Attributes:
        part: LDraw part number without ``.dat`` (e.g. ``"3001"``).
        color: LDraw colour code.
        x: anchor stud column (backend-defined anchor).
        y: anchor stud row.
        layer: lowest plate layer the part occupies.
        yaw: rotation about the vertical axis in degrees (0, 90, 180, 270).
        cells: every grid cell ``(x, y, layer)`` the part occupies.
        step: 0-based build step the part is placed in.
        category: part family (``brick``, ``plate``, ``slope``, ``tile`` ...).
        backend_key: the backend's own part identifier, for round trips.
        unit: parts of one step that share a ``unit`` number are put together
            in the hand first and then placed as one piece (a part that hangs
            below the part holding it); ``None`` for parts placed on their own.
    """

    part: str
    color: int
    x: int
    y: int
    layer: int
    yaw: int
    cells: tuple[Cell, ...]
    step: int
    category: str = "brick"
    backend_key: str = ""
    unit: int | None = None

    def __post_init__(self) -> None:
        if not self.cells:
            msg = f"part {self.part} occupies no cells"
            raise ValueError(msg)
        if self.step < 0:
            msg = f"part {self.part} has negative step {self.step}"
            raise ValueError(msg)

    @property
    def bounds(self) -> tuple[Cell, Cell]:
        """Inclusive ``(min_cell, max_cell)`` of the occupied cells."""
        xs, ys, zs = zip(*self.cells, strict=True)
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


@dataclass(frozen=True, slots=True)
class BuildStep:
    """Metadata of one build step (its parts carry the step index).

    Attributes:
        submodel: name of the subassembly this step builds separately on the
            table, or ``None`` for a step on the main model.
        attaches: name of a finished subassembly this step seats onto the main
            model (such steps place no individual parts).
        stable: verdict on the model as built after this step: ``True`` it
            stands on its own, ``False`` it needs a supporting hand until a
            later step, ``None`` not checked (layer-order steps).
        fragile: stable, but pressing the new parts on firmly may break it.
        section: title of a build section that starts with this step (e.g.
            "Head"), in the language of the instructions; ``None``: the
            section of the step before continues.
        text: a short instruction for this step in plain words, in the
            language of the instructions (``None``: none).
    """

    submodel: str | None = None
    attaches: str | None = None
    stable: bool | None = None
    fragile: bool = False
    section: str | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        if self.submodel is not None and self.attaches is not None:
            msg = "a step cannot both build and attach a subassembly"
            raise ValueError(msg)
        for label, value, limit in (
            ("section", self.section, MAX_SECTION_CHARS),
            ("text", self.text, MAX_STEP_TEXT_CHARS),
        ):
            if value is not None and not 0 < len(value.strip()) <= limit:
                msg = f"step {label} must have 1-{limit} characters, got {value!r}"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BrickModel:
    """An ordered, immutable collection of placed parts with build steps."""

    name: str
    parts: tuple[PlacedPart, ...]
    steps: tuple[BuildStep, ...]
    colors: dict[int, ColorInfo] = field(default_factory=dict)
    """Display info for every colour code used by ``parts``."""
    source: str = ""
    """Free-form provenance, e.g. ``legolization 0.5.0, strategy luo, seed 0``."""
    mass_g: float | None = None
    """Estimated mass of all parts in grams (``None``: unknown)."""
    buildable: bool | None = None
    """Backend verdict on the finished model: stable, one piece, nothing loose
    (``None``: not checked)."""

    def __post_init__(self) -> None:
        if self.parts and not self.steps:
            msg = "a model with parts needs at least one step"
            raise ValueError(msg)
        if bad := [p.part for p in self.parts if p.step >= self.step_count]:
            msg = f"parts {bad[:5]} reference steps beyond step_count={self.step_count}"
            raise ValueError(msg)
        built = {s.submodel for s in self.steps if s.submodel is not None}
        attached = [s.attaches for s in self.steps if s.attaches is not None]
        if missing := sorted(set(attached) - built):
            msg = f"steps attach unknown subassemblies: {', '.join(missing)}"
            raise ValueError(msg)

    @property
    def step_count(self) -> int:
        """Number of build steps, including subassembly steps."""
        return len(self.steps)

    @property
    def main_step_count(self) -> int:
        """Steps on the main model (what a flat ``.ldr`` shows as ``0 STEP``)."""
        return sum(1 for s in self.steps if s.submodel is None)

    @property
    def submodels(self) -> tuple[str, ...]:
        """Names of subassemblies, in build order."""
        return tuple(
            dict.fromkeys(s.submodel for s in self.steps if s.submodel is not None)
        )

    @property
    def part_count(self) -> int:
        """Total number of parts."""
        return len(self.parts)

    def parts_in_step(self, step: int) -> tuple[PlacedPart, ...]:
        """Parts placed in the given 0-based step."""
        return tuple(p for p in self.parts if p.step == step)

    def size_mm(self) -> tuple[float, float, float]:
        """Width, depth and height of the built model in millimetres.

        Width/depth follow the grid ``x``/``y`` axes (8 mm per stud); the
        height counts plates (3.2 mm) plus the studs on top (1.7 mm).
        """
        (x0, y0, z0), (x1, y1, z1) = self.bounds()
        return (
            (x1 - x0 + 1) * MM_PER_STUD,
            (y1 - y0 + 1) * MM_PER_STUD,
            (z1 - z0 + 1) * MM_PER_PLATE + STUD_HEIGHT_MM,
        )

    def bill_of_materials(self) -> dict[tuple[str, int], int]:
        """Quantity per ``(part, colour)``, sorted by part then colour."""
        counts = Counter((p.part, p.color) for p in self.parts)
        return dict(sorted(counts.items()))

    def occupied_cells(self) -> frozenset[Cell]:
        """Union of all occupied cells."""
        return frozenset(cell for p in self.parts for cell in p.cells)

    def bounds(self) -> tuple[Cell, Cell]:
        """Inclusive ``(min_cell, max_cell)`` over all parts."""
        if not self.parts:
            msg = "an empty model has no bounds"
            raise ValueError(msg)
        lows, highs = zip(*(p.bounds for p in self.parts), strict=True)
        return (
            (min(c[0] for c in lows), min(c[1] for c in lows), min(c[2] for c in lows)),
            (
                max(c[0] for c in highs),
                max(c[1] for c in highs),
                max(c[2] for c in highs),
            ),
        )

    # ------------------------------------------------------------ JSON
    def to_dict(self) -> dict[str, Any]:
        """Plain-data representation (JSON-safe)."""
        return {
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "source": self.source,
            "mass_g": self.mass_g,
            "buildable": self.buildable,
            "steps": [asdict(step) for step in self.steps],
            "colors": {str(code): asdict(info) for code, info in self.colors.items()},
            "parts": [
                {**asdict(p), "cells": [list(c) for c in p.cells]} for p in self.parts
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrickModel:
        """Inverse of :meth:`to_dict`.

        Raises:
            ValueError: on an unknown schema version or malformed data.
        """
        if data.get("schema") not in READABLE_SCHEMAS:
            msg = f"unsupported brick model schema {data.get('schema')!r}"
            raise ValueError(msg)
        parts = tuple(
            PlacedPart(
                **{k: v for k, v in raw.items() if k != "cells"},
                cells=tuple((int(c[0]), int(c[1]), int(c[2])) for c in raw["cells"]),
            )
            for raw in data["parts"]
        )
        colors = {int(code): ColorInfo(**info) for code, info in data["colors"].items()}
        return cls(
            name=str(data["name"]),
            parts=parts,
            steps=tuple(BuildStep(**step) for step in data["steps"]),
            colors=colors,
            source=str(data.get("source", "")),
            mass_g=None if data.get("mass_g") is None else float(data["mass_g"]),
            buildable=(
                None if data.get("buildable") is None else bool(data["buildable"])
            ),
        )

    def to_json(self) -> str:
        """Serialise to a JSON string."""
        return json.dumps(self.to_dict(), indent=1)

    @classmethod
    def from_json(cls, text: str) -> BrickModel:
        """Parse a JSON string produced by :meth:`to_json`."""
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            msg = "brick model JSON must be an object"
            raise ValueError(msg)
        return cls.from_dict(loaded)

    def save(self, path: Path) -> Path:
        """Write the model as JSON to ``path`` and return it."""
        path.write_text(self.to_json() + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> BrickModel:
        """Read a model written by :meth:`save`."""
        return cls.from_json(path.read_text(encoding="utf-8"))
