# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Loader protocol, registry by file suffix, and the ingest data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

    import trimesh
    from numpy.typing import NDArray


class IngestError(ValueError):
    """An input file cannot be read or turned into a usable mesh."""


@dataclass(frozen=True, slots=True)
class RawModel:
    """What a loader returns: one or more parts in millimetres, file orientation.

    Attributes:
        parts: the bodies/objects of the file, transforms already applied.
        names: one display name per part.
        notes: loader remarks worth showing (e.g. assumed units).
    """

    parts: tuple[trimesh.Trimesh, ...]
    names: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.parts:
            msg = "the file contains no mesh geometry"
            raise IngestError(msg)
        if len(self.names) != len(self.parts):
            msg = "one name per part required"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class MeshModel:
    """A normalised input model: z up, millimetres, outward-facing normals.

    ``mesh`` is a shared trimesh object; treat it as read-only.
    ``face_part`` maps every face to the index of the part it came from (used
    for per-part colours in Phase 3).
    """

    mesh: trimesh.Trimesh
    source: Path
    part_names: tuple[str, ...]
    watertight: bool
    warnings: tuple[str, ...] = ()
    face_part: NDArray[np.int32] = field(
        default_factory=lambda: np.zeros(0, dtype=np.int32), repr=False, compare=False
    )

    @property
    def part_count(self) -> int:
        """Number of parts the file contained."""
        return len(self.part_names)


class Loader(Protocol):
    """Reads one family of file formats."""

    suffixes: frozenset[str]
    """Lower-case suffixes including the dot, e.g. ``{".stl"}``."""

    def load(self, path: Path) -> RawModel:
        """Read ``path``; raise :class:`IngestError` on unusable input."""
        ...


_REGISTRY: dict[str, Loader] = {}


def register(loader: Loader) -> Loader:
    """Register ``loader`` for all its suffixes (later registrations win)."""
    for suffix in loader.suffixes:
        _REGISTRY[suffix.lower()] = loader
    return loader


def loader_for(path: Path) -> Loader:
    """Return the loader responsible for ``path``'s suffix.

    Raises:
        IngestError: for unsupported file types.
    """
    suffix = path.suffix.lower()
    try:
        return _REGISTRY[suffix]
    except KeyError:
        supported = ", ".join(supported_suffixes())
        msg = f"unsupported input format {suffix or '(none)'!r}; supported: {supported}"
        raise IngestError(msg) from None


def supported_suffixes() -> tuple[str, ...]:
    """All registered suffixes, sorted."""
    return tuple(sorted(_REGISTRY))
