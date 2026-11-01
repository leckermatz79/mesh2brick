# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""3MF reader: core specification plus the production extension.

Why our own reader: slicer project files (Bambu Studio, PrusaSlicer, Orca)
and many CAD exports use the 3MF *production extension*, where the root model
only references objects that live in other ``.model`` files of the archive
(``<component p:path="/3D/Objects/object_1.model" .../>``). Generic loaders
that read only ``3D/3dmodel.model`` silently lose that geometry.

Supported: objects with meshes, nested components (with or without
``p:path``), build items with transforms, ``unit`` (micron ... meter).
Ignored for now: materials/colours (Phase 3), beam lattices, slices.
Only the standard library is used; parsing is streamed (``iterparse``).
"""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from typing import IO, TYPE_CHECKING, Final

import numpy as np
import trimesh

from mesh2brick.ingest.base import IngestError, RawModel

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

UNIT_TO_MM: Final[dict[str, float]] = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}
_ROOT_REL_TYPE: Final = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
_PRODUCTION_PATH: Final = (
    "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path"
)
_SKIPPED_TYPES: Final = frozenset({"support", "solidsupport", "other"})
_MAX_DEPTH: Final = 32

Key = tuple[str, str]  # (archive path without leading slash, object id)


@dataclass(slots=True)
class _Object:
    name: str
    kind: str
    vertices: NDArray[np.float64] | None = None
    triangles: NDArray[np.int64] | None = None
    components: list[tuple[Key, NDArray[np.float64]]] = field(default_factory=list)


@dataclass(slots=True)
class _ModelFile:
    unit: str
    objects: dict[str, _Object]
    build: list[tuple[Key, NDArray[np.float64]]]


class ThreeMFLoader:
    """Loader for ``.3mf`` archives."""

    suffixes: frozenset[str] = frozenset({".3mf"})

    def load(self, path: Path) -> RawModel:
        """Read every build item of the archive, in millimetres.

        Raises:
            IngestError: if the archive or its XML is broken.
        """
        try:
            with zipfile.ZipFile(path) as archive:
                return _Reader(archive).read()
        except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError) as error:
            if isinstance(error, IngestError):
                raise
            msg = f"cannot read 3MF file {path.name}: {error}"
            raise IngestError(msg) from error


class _Reader:
    def __init__(self, archive: zipfile.ZipFile) -> None:
        self._archive = archive
        self._names = {name.lower(): name for name in archive.namelist()}
        self._files: dict[str, _ModelFile] = {}

    def read(self) -> RawModel:
        root_path = self._root_model_path()
        root = self._file(root_path)
        scale = UNIT_TO_MM.get(root.unit)
        if scale is None:
            msg = f"unknown 3MF unit {root.unit!r}"
            raise IngestError(msg)
        parts: list[trimesh.Trimesh] = []
        names: list[str] = []
        for key, transform in root.build:
            for name, vertices, triangles in self._instances(key, transform, depth=0):
                mm = vertices * scale
                parts.append(
                    trimesh.Trimesh(vertices=mm, faces=triangles, process=False)
                )
                names.append(name)
        if not parts:
            msg = "the 3MF build contains no printable mesh objects"
            raise IngestError(msg)
        notes = [] if root.unit == "millimeter" else [f"3MF unit {root.unit} -> mm"]
        units = {f.unit for f in self._files.values()}
        if len(units) > 1:
            notes.append(f"mixed units {sorted(units)}; used the root unit {root.unit}")
        return RawModel(parts=tuple(parts), names=tuple(names), notes=tuple(notes))

    # ------------------------------------------------------------ resolution
    def _instances(
        self, key: Key, transform: NDArray[np.float64], depth: int
    ) -> list[tuple[str, NDArray[np.float64], NDArray[np.int64]]]:
        if depth > _MAX_DEPTH:
            msg = "3MF components nest too deeply (cycle?)"
            raise IngestError(msg)
        file = self._file(key[0])
        try:
            obj = file.objects[key[1]]
        except KeyError:
            msg = f"3MF references missing object {key[1]} in /{key[0]}"
            raise IngestError(msg) from None
        if obj.kind in _SKIPPED_TYPES:
            return []
        found: list[tuple[str, NDArray[np.float64], NDArray[np.int64]]] = []
        if obj.vertices is not None and obj.triangles is not None:
            if obj.triangles.size and obj.triangles.max() >= len(obj.vertices):
                msg = f"3MF object {obj.name}: triangle index out of range"
                raise IngestError(msg)
            found.append((obj.name, _apply(transform, obj.vertices), obj.triangles))
        for child, child_transform in obj.components:
            found.extend(self._instances(child, transform @ child_transform, depth + 1))
        return found

    def _file(self, path: str) -> _ModelFile:
        if path not in self._files:
            real = self._names.get(path.lower())
            if real is None:
                msg = f"3MF archive lacks the model part /{path}"
                raise IngestError(msg)
            with self._archive.open(real) as handle:
                self._files[path] = _parse_model(handle, path)
        return self._files[path]

    def _root_model_path(self) -> str:
        rels = self._names.get("_rels/.rels")
        if rels is not None:
            with self._archive.open(rels) as handle:
                for element in ET.parse(handle).getroot():
                    if element.attrib.get("Type") == _ROOT_REL_TYPE:
                        return element.attrib["Target"].lstrip("/")
        for lower, real in self._names.items():
            if lower.endswith("3dmodel.model"):
                return real
        msg = "not a 3MF archive (no 3D model part found)"
        raise IngestError(msg)


def _parse_model(handle: IO[bytes], path: str) -> _ModelFile:
    """Stream-parse one ``.model`` XML part."""
    unit = "millimeter"
    objects: dict[str, _Object] = {}
    build: list[tuple[Key, NDArray[np.float64]]] = []
    current: _Object | None = None
    vertices: list[tuple[str, str, str]] = []
    triangles: list[tuple[str, str, str]] = []
    # Open elements; finished vertices/triangles are detached from their parent
    # right away so memory stays flat for multi-million-triangle meshes.
    stack: list[ET.Element] = []
    for event, element in ET.iterparse(handle, events=("start", "end")):
        tag = element.tag.rpartition("}")[2]
        attrib = element.attrib
        if event == "start":
            stack.append(element)
            if tag == "model":
                unit = attrib.get("unit", "millimeter")
            elif tag == "object":
                current = _Object(
                    name=attrib.get("name", f"object {attrib['id']}"),
                    kind=attrib.get("type", "model"),
                )
                objects[attrib["id"]] = current
                vertices, triangles = [], []
            continue
        stack.pop()
        match tag:
            case "vertex":
                vertices.append((attrib["x"], attrib["y"], attrib["z"]))
                del stack[-1][-1]
            case "triangle":
                triangles.append((attrib["v1"], attrib["v2"], attrib["v3"]))
                del stack[-1][-1]
            case "mesh" if current is not None:
                current.vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
                current.triangles = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
                vertices, triangles = [], []
                element.clear()
            case "component" if current is not None:
                target = _target(attrib, path)
                current.components.append((target, _transform(attrib)))
            case "item":
                build.append((_target(attrib, path), _transform(attrib)))
            case "object":
                current = None
                element.clear()
            case _:
                pass
    return _ModelFile(unit=unit, objects=objects, build=build)


def _target(attrib: dict[str, str], current_path: str) -> Key:
    """Resolve a component/item reference to (archive path, object id)."""
    ref = attrib.get(_PRODUCTION_PATH)
    path = posixpath.normpath(ref).lstrip("/") if ref else current_path
    return (path, attrib["objectid"])


def _transform(attrib: dict[str, str]) -> NDArray[np.float64]:
    """3MF's 12-value row-vector transform as a 4x4 column-vector matrix."""
    matrix = np.eye(4)
    if "transform" in attrib:
        values = np.asarray(attrib["transform"].split(), dtype=np.float64)
        if values.size != 12:  # noqa: PLR2004 - fixed by the 3MF spec
            msg = f"3MF transform needs 12 numbers, got {values.size}"
            raise IngestError(msg)
        matrix[:3, :4] = values.reshape(4, 3).T
    return matrix


def _apply(
    transform: NDArray[np.float64], vertices: NDArray[np.float64]
) -> NDArray[np.float64]:
    result: NDArray[np.float64] = vertices @ transform[:3, :3].T + transform[:3, 3]
    return result
