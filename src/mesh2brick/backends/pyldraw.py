# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Access to the local LDraw parts library through `pyldraw3`.

* :func:`library_status`: is the library installed, are the generated
  ``ldraw.library`` modules importable?
* :func:`part_geometry`: bounding box and studs of a part (resolved subfile
  tree), the raw material for :class:`mesh2brick.catalog.parts.PartSpec`.
* :func:`library_parts`: every part number and description in ``parts.lst``.
* :func:`library_release`: the library's release tag (cache key).
"""

from __future__ import annotations

import importlib
import importlib.metadata
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from ldraw.config import Config
from ldraw.errors import NoGeometryError, PartError, PartNotFoundError
from ldraw.part_geometry import part_bounding_box, part_studs
from ldraw.parts import Parts

from mesh2brick.backends.protocols import BackendError
from mesh2brick.catalog.parts import PartGeometry

VERSION: Final = importlib.metadata.version("pyldraw3")
SETUP_HINT: Final = (
    "install the LDraw parts library once with: "
    "uv run ldraw download --yes && uv run ldraw generate --yes"
)


@dataclass(frozen=True, slots=True)
class LibraryStatus:
    """Where the LDraw library lives and whether it is usable."""

    library_path: Path | None
    generated_path: Path | None
    library_present: bool
    generated_present: bool

    @property
    def ready(self) -> bool:
        """The generated ``ldraw.library`` modules are importable.

        That is all placement and LDraw export need; the raw ``.dat`` parts
        (``library_present``) are only read when generating those modules and,
        from Phase 4, for part geometry.
        """
        return self.generated_present


def library_status() -> LibraryStatus:
    """Inspect pyldraw3's configuration without downloading anything."""
    config = Config.load()
    library = Path(config.ldraw_library_path) if config.ldraw_library_path else None
    generated = Path(config.generated_path) if config.generated_path else None
    # complete.zip unpacks to <path>/ldraw/parts; a hand-installed library may
    # point straight at the ldraw directory.
    library_present = library is not None and any(
        (root / "parts").is_dir() for root in (library, library / "ldraw")
    )
    try:
        importlib.import_module("ldraw.library.colours")
    except ImportError:
        generated_present = False
    else:
        generated_present = True
    return LibraryStatus(
        library_path=library,
        generated_path=generated,
        library_present=library_present,
        generated_present=generated_present,
    )


# --------------------------------------------------------------------------- parts
def _ldraw_root() -> Path:
    """The directory holding ``parts.lst`` and ``parts/``.

    Raises:
        BackendError: if the library is not installed.
    """
    status = library_status()
    if status.library_path is not None:
        for root in (status.library_path / "ldraw", status.library_path):
            if (root / "parts.lst").is_file():
                return root
    msg = f"the LDraw parts library is missing; {SETUP_HINT}"
    raise BackendError(msg)


@lru_cache(maxsize=1)
def _parts() -> Parts:
    return Parts(_ldraw_root() / "parts.lst")


def library_release() -> str:
    """Release tag of the installed library (``_release.txt``), or ``unknown``."""
    try:
        text = (_ldraw_root() / "_release.txt").read_text(encoding="utf-8")
    except (OSError, BackendError):
        return "unknown"
    return text.strip().splitlines()[0] if text.strip() else "unknown"


def library_parts() -> tuple[tuple[str, str], ...]:
    """``(part number, description)`` for every entry of ``parts.lst``."""
    entries: list[tuple[str, str]] = []
    text = (_ldraw_root() / "parts.lst").read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        name, _, description = line.partition(" ")
        if name.lower().endswith(".dat"):
            entries.append((name[:-4], description.strip()))
    return tuple(entries)


def part_exists(part: str) -> bool:
    """Whether ``part`` is a part file of the installed library."""
    root = _ldraw_root()
    return (root / "parts" / f"{part}.dat").is_file()


def describe(part: str) -> str:
    """LDraw description of ``part``; aliases ("~Moved to 3023b") are followed."""
    seen: set[str] = set()
    current = part
    while current not in seen:
        seen.add(current)
        description = _parts().description_for(current) or _first_line(current)
        moved = re.match(r"~Moved to\s+(\S+)", description)
        if moved is None:
            return description
        current = moved.group(1).removesuffix(".dat")
    return part


def _first_line(part: str) -> str:
    """Title line of a part file without the leading ``0`` (or the number)."""
    path = _ldraw_root() / "parts" / f"{part}.dat"
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            first = handle.readline()
    except OSError:
        return part
    return first.removeprefix("0").strip() or part


def part_geometry(part: str) -> PartGeometry:
    """Bounding box and upward studs of ``part`` (LDU).

    Raises:
        BackendError: for unknown parts or parts without geometry.
    """
    parts = _parts()
    try:
        box = part_bounding_box(parts, part)
        studs = part_studs(parts, part)
    except (PartNotFoundError, NoGeometryError, PartError) as error:
        msg = f"LDraw part {part!r}: {error}"
        raise BackendError(msg) from error
    return PartGeometry(
        part=part,
        description=describe(part),
        min_ldu=(float(box.min.x), float(box.min.y), float(box.min.z)),
        max_ldu=(float(box.max.x), float(box.max.y), float(box.max.z)),
        top_studs=sum(1 for stud in studs if float(stud.up.y) < 0),
    )
