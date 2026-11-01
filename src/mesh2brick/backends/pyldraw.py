# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Access to the local LDraw parts library through `pyldraw3`.

Phase 0 only checks that the library is installed and the generated
``ldraw.library`` modules are importable. Part geometry and the full colour
table (for ``color.palette: all``) follow in Phases 3-4.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ldraw.config import Config

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
