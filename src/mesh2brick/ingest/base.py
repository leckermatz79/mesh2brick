# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Loader protocol, registry by file suffix, and the ingest data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal, Protocol

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

    import trimesh
    from numpy.typing import NDArray

    from mesh2brick.config import InputConfig


class IngestError(ValueError):
    """An input file cannot be read or turned into a usable mesh."""


ColorKind = Literal["cad", "vertex", "texture"]
COLOR_KINDS: Final[tuple[ColorKind, ...]] = ("cad", "vertex", "texture")
"""Colour sources from least to most detailed."""


@dataclass(frozen=True, slots=True)
class FaceColors:
    """Colour sources aligned with the faces of one mesh (sRGB, 0-255).

    A face can carry several sources; ``color.mode`` picks the most detailed
    one it allows. Each mask says which faces a source covers.

    Attributes:
        cad: ``(F, 3)`` one colour per face from the file's design data
            (part colours, materials, slicer filaments).
        cad_mask: ``(F,)`` faces that have a ``cad`` colour.
        vertex: ``(F, 3, 3)`` colour per face corner (vertex or face colour
            attributes), interpolated across the face; ``None`` if no face has one.
        vertex_mask: ``(F,)`` faces that have ``vertex`` colours.
        uv: ``(F, 3, 2)`` texture coordinates per face corner (OpenGL
            convention, v points up); ``None`` if no face is textured.
        texture: ``(F,)`` index into ``textures``, -1 for untextured faces.
        textures: ``(H, W, 3)`` sRGB images, material tint already applied.
    """

    cad: NDArray[np.uint8]
    cad_mask: NDArray[np.bool_]
    vertex: NDArray[np.uint8] | None = None
    vertex_mask: NDArray[np.bool_] | None = None
    uv: NDArray[np.float32] | None = None
    texture: NDArray[np.int32] | None = None
    textures: tuple[NDArray[np.uint8], ...] = ()

    def __post_init__(self) -> None:
        faces = len(self.cad)
        sizes = [len(self.cad_mask)] + [
            len(a)
            for a in (self.vertex, self.vertex_mask, self.uv, self.texture)
            if a is not None
        ]
        if any(size != faces for size in sizes):
            msg = "all colour arrays need one entry per face"
            raise ValueError(msg)
        if (self.vertex is None) != (self.vertex_mask is None):
            msg = "vertex colours need a mask"
            raise ValueError(msg)
        if (self.uv is None) != (self.texture is None):
            msg = "texture coordinates need texture indices"
            raise ValueError(msg)

    @property
    def face_count(self) -> int:
        """Number of faces the arrays describe."""
        return len(self.cad)

    def mask(self, kind: ColorKind) -> NDArray[np.bool_]:
        """Faces covered by colour source ``kind``."""
        match kind:
            case "cad":
                return self.cad_mask
            case "vertex":
                if self.vertex_mask is None:
                    return np.zeros(self.face_count, dtype=bool)
                return self.vertex_mask
            case "texture":
                if self.texture is None:
                    return np.zeros(self.face_count, dtype=bool)
                return self.texture >= 0

    @property
    def kinds(self) -> tuple[ColorKind, ...]:
        """Colour sources present on at least one face."""
        return tuple(kind for kind in COLOR_KINDS if self.mask(kind).any())

    @classmethod
    def uniform(cls, rgb: tuple[int, int, int], faces: int) -> FaceColors:
        """One ``cad`` colour on every face."""
        return cls(
            cad=np.tile(np.asarray(rgb, dtype=np.uint8), (faces, 1)),
            cad_mask=np.ones(faces, dtype=bool),
        )


@dataclass(frozen=True, slots=True)
class RawModel:
    """What a loader returns: one or more parts in millimetres, file orientation.

    Attributes:
        parts: the bodies/objects of the file, transforms already applied.
        names: one display name per part.
        notes: loader remarks worth showing (e.g. assumed units).
        colors: per part the colours the loader read itself (3MF materials,
            slicer filaments), ``None`` where it has none. Empty: colours come
            from the trimesh visuals of the parts (OBJ, PLY, glTF).
    """

    parts: tuple[trimesh.Trimesh, ...]
    names: tuple[str, ...]
    notes: tuple[str, ...] = ()
    colors: tuple[FaceColors | None, ...] = ()

    def __post_init__(self) -> None:
        if not self.parts:
            msg = "the file contains no mesh geometry"
            raise IngestError(msg)
        if len(self.names) != len(self.parts):
            msg = "one name per part required"
            raise ValueError(msg)
        if self.colors and len(self.colors) != len(self.parts):
            msg = "colours must be given for every part or none"
            raise ValueError(msg)
        for part, colors in zip(self.parts, self.colors, strict=False):
            if colors is not None and colors.face_count != len(part.faces):
                msg = "part colours need one entry per face"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class MeshModel:
    """A normalised input model: z up, millimetres, outward-facing normals.

    ``mesh`` is a shared trimesh object without visuals; treat it as
    read-only. ``face_part`` maps every face to the index of the part it came
    from (-1 for faces added by hole filling). ``colors`` holds the colour
    sources aligned with ``mesh.faces`` (``None``: the file has no colours).
    """

    mesh: trimesh.Trimesh
    source: Path
    part_names: tuple[str, ...]
    watertight: bool
    warnings: tuple[str, ...] = ()
    face_part: NDArray[np.int32] = field(
        default_factory=lambda: np.zeros(0, dtype=np.int32), repr=False, compare=False
    )
    colors: FaceColors | None = field(default=None, repr=False, compare=False)

    @property
    def part_count(self) -> int:
        """Number of parts the file contained."""
        return len(self.part_names)


class Loader(Protocol):
    """Reads one family of file formats."""

    suffixes: frozenset[str]
    """Lower-case suffixes including the dot, e.g. ``{".stl"}``."""

    def load(self, path: Path, config: InputConfig | None = None) -> RawModel:
        """Read ``path``; raise :class:`IngestError` on unusable input.

        ``config`` carries reader options (e.g. the STEP tolerance).
        """
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
