# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""``PartSpec``: what a part is, derived from its LDraw geometry.

The backend (pyldraw3) resolves a part's subfile tree and reports its
bounding box and studs (:class:`PartGeometry`). :func:`derive_spec` turns that
into a stud-grid description: footprint in studs, height in plates, number of
studs on top and a category from the LDraw description. Specs are cached as
JSON per LDraw library release, so listing the catalogue stays fast and works
offline (SPEC Phase 4, ADR 0009).

LDraw facts: 1 stud = 20 LDU, 1 plate = 8 LDU; parts hang from their origin
towards +Y, studs point towards -Y.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

SpecCategory = Literal["brick", "plate", "tile", "slope", "other"]
SPEC_CATEGORIES: Final[tuple[SpecCategory, ...]] = (
    "brick",
    "plate",
    "tile",
    "slope",
    "other",
)
CACHE_SCHEMA: Final = 1
_LDU_PER_STUD: Final = 20.0
_LDU_PER_PLATE: Final = 8.0


@dataclass(frozen=True, slots=True)
class PartGeometry:
    """A part's resolved geometry as the library reports it (LDU)."""

    part: str
    description: str
    min_ldu: tuple[float, float, float]
    max_ldu: tuple[float, float, float]
    top_studs: int
    """Studs pointing up (-Y); tubes and anti-studs underneath do not count."""


@dataclass(frozen=True, slots=True)
class PartSpec:
    """A part on the stud grid."""

    part: str
    """LDraw part number (file name without ``.dat``)."""
    name: str
    """LDraw description, single-spaced (``"Brick 2 x 4"``)."""
    category: SpecCategory
    width: int
    """Shorter footprint side in studs."""
    length: int
    """Longer footprint side in studs."""
    height_plates: int
    """Body height in plates (a brick is 3)."""
    top_studs: int

    @property
    def size(self) -> str:
        """Human-readable size, e.g. ``2 x 4 x 1 brick`` or ``1 x 2 plate``."""
        footprint = f"{self.width} x {self.length}"
        if self.height_plates % 3 == 0 and self.height_plates:
            bricks = self.height_plates // 3
            return f"{footprint} x {bricks} brick{'s' if bricks > 1 else ''}"
        plates = self.height_plates
        return f"{footprint} x {plates} plate{'s' if plates != 1 else ''}"


def clean_description(text: str) -> str:
    """LDraw description with single spaces and without alias markers."""
    return " ".join(text.lstrip("~=_|").split())


def category_of(description: str, top_studs: int) -> SpecCategory:
    """Category from the LDraw description (``Slope Brick 45 2 x 2`` -> slope).

    Tiles are plates without studs; LDraw calls them "Tile".
    """
    words = clean_description(description).lower().split()
    head = set(words[:3])
    if "slope" in head:
        return "slope"
    if words[:1] == ["tile"] or (words[:1] == ["plate"] and top_studs == 0):
        return "tile"
    if words[:1] == ["plate"]:
        return "plate"
    if words[:1] == ["brick"]:
        return "brick"
    return "other"


def derive_spec(geometry: PartGeometry) -> PartSpec:
    """Stud-grid spec of a part from its bounding box and studs."""
    (x0, _y0, z0), (x1, y1, z1) = geometry.min_ldu, geometry.max_ldu
    sides = sorted(
        (
            max(1, round((x1 - x0) / _LDU_PER_STUD)),
            max(1, round((z1 - z0) / _LDU_PER_STUD)),
        )
    )
    return PartSpec(
        part=geometry.part,
        name=clean_description(geometry.description),
        category=category_of(geometry.description, geometry.top_studs),
        width=sides[0],
        length=sides[1],
        height_plates=max(1, round(y1 / _LDU_PER_PLATE)),
        top_studs=geometry.top_studs,
    )


def nominal_size(description: str) -> tuple[int, int] | None:
    """Footprint named in a description (``Plate 2 x 8`` -> (2, 8)), sorted."""
    match = re.search(r"(\d+)\s*x\s*(\d+)", clean_description(description))
    if match is None:
        return None
    a, b = sorted((int(match.group(1)), int(match.group(2))))
    return (a, b)


# --------------------------------------------------------------------------- cache
def load_cache(path: Path, release: str) -> dict[str, PartSpec]:
    """Specs cached for LDraw ``release`` (empty if missing or outdated)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("schema") != CACHE_SCHEMA or data.get("release") != release:
        return {}
    return {code: PartSpec(**row) for code, row in data.get("specs", {}).items()}


def save_cache(path: Path, release: str, specs: dict[str, PartSpec]) -> None:
    """Write ``specs`` for LDraw ``release`` (creates the directory)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": CACHE_SCHEMA,
        "release": release,
        "specs": {code: asdict(spec) for code, spec in sorted(specs.items())},
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def part_specs(
    parts: Iterable[str],
    geometry: Callable[[str], PartGeometry],
    *,
    cache: Path | None = None,
    release: str = "",
) -> dict[str, PartSpec]:
    """Specs for ``parts``, derived through ``geometry`` and cached in ``cache``.

    Raises:
        Whatever ``geometry`` raises for unknown parts.
    """
    known = load_cache(cache, release) if cache is not None else {}
    result: dict[str, PartSpec] = {}
    added = False
    for part in dict.fromkeys(parts):
        spec = known.get(part)
        if spec is None:
            spec = derive_spec(geometry(part))
            known[part] = spec
            added = True
        result[part] = spec
    if cache is not None and added:
        save_cache(cache, release, known)
    return result


def spec_cache_path(cache_dir: Path, release: str) -> Path:
    """Cache file for one LDraw library release."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", release) or "unknown"
    return cache_dir / f"partspecs-{safe}.json"
