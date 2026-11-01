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

Colours (the ``cad`` colour source):

* core ``<basematerials>`` (``displaycolor``) and the materials extension's
  ``<colorgroup>``, referenced by objects (``pid``/``pindex``) and triangles
  (``pid``/``p1``),
* slicer projects, which win because they describe the actual print:
  Bambu Studio / Orca Slicer (extruder per part in
  ``Metadata/model_settings.config``, ``filament_colour`` in
  ``Metadata/project_settings.config``) and PrusaSlicer (triangle ranges per
  volume in ``Metadata/Slic3r_PE_model.config``, colours in
  ``Metadata/Slic3r_PE.config``). Their modifier, negative and support-helper
  volumes are not part of the model and are skipped.

Ignored for now: painted colours (multi-material painting), textures, beam
lattices, slices. Only the standard library is used; parsing is streamed
(``iterparse``).
"""

from __future__ import annotations

import json
import posixpath
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from typing import IO, TYPE_CHECKING, Final

import numpy as np
import trimesh

from mesh2brick.ingest.base import FaceColors, IngestError, RawModel
from mesh2brick.ingest.colors import parse_hex_color

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from mesh2brick.config import InputConfig

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
_PAINT_ATTRIBUTES: Final = frozenset({"paint_color", "mmu_segmentation"})
_BAMBU_MODEL: Final = "metadata/model_settings.config"
_BAMBU_PROJECT: Final = "metadata/project_settings.config"
_PRUSA_MODEL: Final = "metadata/slic3r_pe_model.config"
_PRUSA_PROJECT: Final = "metadata/slic3r_pe.config"
_BAMBU_HELPER_PARTS: Final = frozenset(
    {"negative_part", "modifier_part", "support_blocker", "support_enforcer"}
)
_PRUSA_MODEL_PART: Final = "ModelPart"

Key = tuple[str, str]  # (archive path without leading slash, object id)
RGB = tuple[int, int, int]


@dataclass(slots=True)
class _Object:
    name: str
    kind: str
    pid: str | None = None
    pindex: int = 0
    vertices: NDArray[np.float64] | None = None
    triangles: NDArray[np.int64] | None = None
    components: list[tuple[Key, NDArray[np.float64]]] = field(default_factory=list)
    triangle_properties: dict[int, tuple[str | None, int | None]] = field(
        default_factory=dict
    )
    """Sparse per-triangle ``(pid, p1)`` overrides."""


@dataclass(slots=True)
class _ModelFile:
    unit: str
    objects: dict[str, _Object]
    build: list[tuple[Key, NDArray[np.float64]]]
    materials: dict[str, list[RGB | None]] = field(default_factory=dict)
    """Property groups (basematerials, colorgroups) by resource id."""
    painted: bool = False
    textured: bool = False

    def color(self, pid: str | None, index: int | None) -> RGB | None:
        """Colour of property ``index`` in group ``pid`` (``None`` if none)."""
        group = self.materials.get(pid or "")
        if group is None or index is None or not 0 <= index < len(group):
            return None
        return group[index]


@dataclass(frozen=True, slots=True)
class _Instance:
    name: str
    vertices: NDArray[np.float64]
    triangles: NDArray[np.int64]
    colors: FaceColors | None


@dataclass(frozen=True, slots=True)
class _Volume:
    first: int
    last: int
    extruder: int
    printable: bool


@dataclass(slots=True)
class _SlicerColors:
    """Filament assignment from a slicer project inside the 3MF."""

    source: str
    filaments: tuple[RGB | None, ...]
    objects: dict[str, int] = field(default_factory=dict)
    """Root object id -> extruder (1-based)."""
    parts: dict[tuple[str, str], int] = field(default_factory=dict)
    """(root object id, component object id) -> extruder (Bambu, Orca)."""
    helpers: set[tuple[str, str]] = field(default_factory=set)
    """Components that are modifiers/negative volumes (Bambu, Orca)."""
    volumes: dict[str, list[_Volume]] = field(default_factory=dict)
    """Root object id -> triangle ranges (PrusaSlicer)."""

    def rgb(self, extruder: int | None) -> RGB | None:
        if extruder is None or not 1 <= extruder <= len(self.filaments):
            return None
        return self.filaments[extruder - 1]


class ThreeMFLoader:
    """Loader for ``.3mf`` archives."""

    suffixes: frozenset[str] = frozenset({".3mf"})

    def load(
        self,
        path: Path,
        config: InputConfig | None = None,  # noqa: ARG002 - no options yet
    ) -> RawModel:
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
        self._slicer: _SlicerColors | None = None
        self._skipped_helpers = 0

    def read(self) -> RawModel:
        root_path = self._root_model_path()
        root = self._file(root_path)
        scale = UNIT_TO_MM.get(root.unit)
        if scale is None:
            msg = f"unknown 3MF unit {root.unit!r}"
            raise IngestError(msg)
        self._slicer = _read_slicer_colors(self._archive, self._names)
        self._skipped_helpers = 0
        instances: list[_Instance] = []
        for key, transform in root.build:
            instances.extend(
                self._instances(key, transform, depth=0, top=key[1], part=None)
            )
        if not instances:
            msg = "the 3MF build contains no printable mesh objects"
            raise IngestError(msg)
        parts = [
            trimesh.Trimesh(
                vertices=i.vertices * scale, faces=i.triangles, process=False
            )
            for i in instances
        ]
        notes = [] if root.unit == "millimeter" else [f"3MF unit {root.unit} -> mm"]
        units = {f.unit for f in self._files.values()}
        if len(units) > 1:
            notes.append(f"mixed units {sorted(units)}; used the root unit {root.unit}")
        notes.extend(self._color_notes(instances))
        colors = tuple(i.colors for i in instances)
        return RawModel(
            parts=tuple(parts),
            names=tuple(i.name for i in instances),
            notes=tuple(notes),
            colors=colors if any(c is not None for c in colors) else (),
        )

    def _color_notes(self, instances: list[_Instance]) -> list[str]:
        notes: list[str] = []
        if self._slicer is not None and any(i.colors for i in instances):
            used = sum(1 for c in self._slicer.filaments if c is not None)
            notes.append(f"colours from {self._slicer.source} ({used} filaments)")
        if self._skipped_helpers:
            notes.append(
                f"skipped {self._skipped_helpers} modifier/negative volume(s) "
                "of the slicer project"
            )
        if any(f.painted for f in self._files.values()):
            notes.append("painted colours (multi-material painting) are not read yet")
        if any(f.textured for f in self._files.values()):
            notes.append("3MF textures are not read yet; using material colours")
        return notes

    # ------------------------------------------------------------ resolution
    def _instances(
        self,
        key: Key,
        transform: NDArray[np.float64],
        depth: int,
        top: str,
        part: str | None,
    ) -> list[_Instance]:
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
        found: list[_Instance] = []
        if obj.vertices is not None and obj.triangles is not None:
            if obj.triangles.size and obj.triangles.max() >= len(obj.vertices):
                msg = f"3MF object {obj.name}: triangle index out of range"
                raise IngestError(msg)
            found.append(
                self._mesh_instance(
                    file,
                    obj,
                    _apply(transform, obj.vertices),
                    obj.triangles,
                    where=(depth, top, part),
                )
            )
        for child, child_transform in obj.components:
            child_part = child[1] if depth == 0 else part
            slicer = self._slicer
            if slicer is not None and (top, child_part or "") in slicer.helpers:
                self._skipped_helpers += 1
                continue
            found.extend(
                self._instances(
                    child, transform @ child_transform, depth + 1, top, child_part
                )
            )
        return found

    def _mesh_instance(
        self,
        file: _ModelFile,
        obj: _Object,
        vertices: NDArray[np.float64],
        triangles: NDArray[np.int64],
        *,
        where: tuple[int, str, str | None],
    ) -> _Instance:
        """One mesh object, coloured by its slicer part or its materials.

        ``where``: nesting depth, root object id and component (part) id.
        """
        depth, top, part = where
        colors = _material_colors(file, obj, len(triangles))
        slicer = self._slicer
        if slicer is None:
            return _Instance(obj.name, vertices, triangles, colors)
        volumes = slicer.volumes.get(top) if depth == 0 else None
        if volumes:
            return self._prusa_instance(slicer, obj.name, vertices, triangles, volumes)
        extruder = slicer.parts.get((top, part)) if part is not None else None
        if extruder is None:
            extruder = slicer.objects.get(top)
        rgb = slicer.rgb(extruder)
        if rgb is not None:
            colors = FaceColors.uniform(rgb, len(triangles))
        return _Instance(obj.name, vertices, triangles, colors)

    def _prusa_instance(
        self,
        slicer: _SlicerColors,
        name: str,
        vertices: NDArray[np.float64],
        triangles: NDArray[np.int64],
        volumes: list[_Volume],
    ) -> _Instance:
        """PrusaSlicer: one mesh per object, volumes are triangle ranges."""
        count = len(triangles)
        keep = np.ones(count, dtype=bool)
        rgb = np.zeros((count, 3), dtype=np.uint8)
        known = np.zeros(count, dtype=bool)
        for volume in volumes:
            span = slice(max(volume.first, 0), min(volume.last + 1, count))
            if not volume.printable:
                keep[span] = False
                self._skipped_helpers += 1
                continue
            color = slicer.rgb(volume.extruder)
            if color is not None:
                rgb[span] = color
                known[span] = True
        colors = (
            FaceColors(cad=rgb[keep], cad_mask=known[keep]) if known.any() else None
        )
        return _Instance(name, vertices, triangles[keep], colors)

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
    parser = _ModelParser(path)
    # Open elements; finished vertices/triangles are detached from their parent
    # right away so memory stays flat for multi-million-triangle meshes.
    stack: list[ET.Element] = []
    for event, element in ET.iterparse(handle, events=("start", "end")):
        tag = element.tag.rpartition("}")[2]
        if event == "start":
            stack.append(element)
            parser.start(tag, element.attrib)
            continue
        stack.pop()
        if parser.end(tag, element.attrib):
            del stack[-1][-1]
        elif tag in {"mesh", "object"}:
            element.clear()
    return parser.file


class _ModelParser:
    """Event handlers for :func:`_parse_model`."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.file = _ModelFile(unit="millimeter", objects={}, build=[])
        self.current: _Object | None = None
        self.group: list[RGB | None] | None = None
        self.vertices: list[tuple[str, str, str]] = []
        self.triangles: list[tuple[str, str, str]] = []

    def start(self, tag: str, attrib: dict[str, str]) -> None:
        match tag:
            case "model":
                self.file.unit = attrib.get("unit", "millimeter")
            case "object":
                self.current = _Object(
                    name=attrib.get("name", f"object {attrib['id']}"),
                    kind=attrib.get("type", "model"),
                    pid=attrib.get("pid"),
                    pindex=int(attrib.get("pindex", "0")),
                )
                self.file.objects[attrib["id"]] = self.current
                self.vertices, self.triangles = [], []
            case "basematerials" | "colorgroup":
                self.group = self.file.materials.setdefault(attrib["id"], [])
            case "texture2dgroup":
                self.file.textured = True
            case _:
                pass

    def end(self, tag: str, attrib: dict[str, str]) -> bool:
        """Handle a closing tag; ``True`` if the element can be detached."""
        match tag:
            case "vertex":
                self.vertices.append((attrib["x"], attrib["y"], attrib["z"]))
                return True
            case "triangle":
                self._triangle(attrib)
                return True
            case "mesh" if self.current is not None:
                self.current.vertices = np.asarray(
                    self.vertices, dtype=np.float64
                ).reshape(-1, 3)
                self.current.triangles = np.asarray(
                    self.triangles, dtype=np.int64
                ).reshape(-1, 3)
                self.vertices, self.triangles = [], []
            case "base" if self.group is not None:
                self.group.append(parse_hex_color(attrib.get("displaycolor", "")))
            case "color" if self.group is not None:
                self.group.append(parse_hex_color(attrib.get("color", "")))
            case "basematerials" | "colorgroup":
                self.group = None
            case "component" if self.current is not None:
                target = _target(attrib, self.path)
                self.current.components.append((target, _transform(attrib)))
            case "item":
                self.file.build.append((_target(attrib, self.path), _transform(attrib)))
            case "object":
                self.current = None
            case _:
                pass
        return False

    def _triangle(self, attrib: dict[str, str]) -> None:
        self.triangles.append((attrib["v1"], attrib["v2"], attrib["v3"]))
        if len(attrib) == 3:  # noqa: PLR2004 - plain triangle: v1, v2, v3 only
            return
        if self.current is not None and ("pid" in attrib or "p1" in attrib):
            p1 = attrib.get("p1")
            self.current.triangle_properties[len(self.triangles) - 1] = (
                attrib.get("pid"),
                None if p1 is None else int(p1),
            )
        if not self.file.painted and any(
            name.rpartition("}")[2] in _PAINT_ATTRIBUTES for name in attrib
        ):
            self.file.painted = True


def _material_colors(file: _ModelFile, obj: _Object, count: int) -> FaceColors | None:
    """Per-triangle colours from 3MF property references (``None`` if none)."""
    default = file.color(obj.pid, obj.pindex)
    if default is None and not obj.triangle_properties:
        return None
    rgb = np.zeros((count, 3), dtype=np.uint8)
    known = np.zeros(count, dtype=bool)
    if default is not None:
        rgb[:] = default
        known[:] = True
    for index, (pid, p1) in obj.triangle_properties.items():
        if index >= count:
            continue
        color = file.color(pid or obj.pid, obj.pindex if p1 is None else p1)
        if color is not None:
            rgb[index] = color
            known[index] = True
    return FaceColors(cad=rgb, cad_mask=known) if known.any() else None


# ---------------------------------------------------------------- slicer projects
def _read_slicer_colors(
    archive: zipfile.ZipFile, names: dict[str, str]
) -> _SlicerColors | None:
    """Filament colours of a Bambu/Orca or PrusaSlicer project, if present."""
    try:
        if _BAMBU_MODEL in names and _BAMBU_PROJECT in names:
            return _bambu(
                archive.read(names[_BAMBU_MODEL]), archive.read(names[_BAMBU_PROJECT])
            )
        if _PRUSA_MODEL in names and _PRUSA_PROJECT in names:
            return _prusa(
                archive.read(names[_PRUSA_MODEL]), archive.read(names[_PRUSA_PROJECT])
            )
    except (ET.ParseError, ValueError, KeyError, UnicodeDecodeError):
        return None  # a broken slicer side file must not block the geometry
    return None


def _bambu(model_config: bytes, project_config: bytes) -> _SlicerColors | None:
    """Bambu Studio / Orca Slicer: extruder per object and part, filament list."""
    project = json.loads(project_config.decode("utf-8"))
    raw = project.get("filament_colour") or []
    filaments = tuple(parse_hex_color(str(c)) for c in raw)
    if not any(filaments):
        return None
    slicer = _SlicerColors(source="Bambu Studio/Orca Slicer", filaments=filaments)
    for obj in ET.fromstring(model_config).iter("object"):
        object_id = obj.get("id", "")
        if (extruder := _metadata_int(obj, "extruder")) is not None:
            slicer.objects[object_id] = extruder
        for part in obj.iter("part"):
            part_id = part.get("id", "")
            if part.get("subtype", "normal_part") in _BAMBU_HELPER_PARTS:
                slicer.helpers.add((object_id, part_id))
            if (extruder := _metadata_int(part, "extruder")) is not None:
                slicer.parts[(object_id, part_id)] = extruder
    return slicer


def _prusa(model_config: bytes, project_config: bytes) -> _SlicerColors | None:
    """PrusaSlicer: volumes as triangle ranges, colours per extruder."""
    settings: dict[str, str] = {}
    for line in project_config.decode("utf-8").splitlines():
        key, sep, value = line.removeprefix(";").partition("=")
        if sep:
            settings[key.strip()] = value.strip()
    extruder = settings.get("extruder_colour", "").split(";")
    filament = settings.get("filament_colour", "").split(";")
    filaments = tuple(
        parse_hex_color(e.strip('"')) or parse_hex_color(f.strip('"'))
        for e, f in zip(
            extruder + [""] * (len(filament) - len(extruder)),
            filament + [""] * (len(extruder) - len(filament)),
            strict=True,
        )
    )
    if not any(filaments):
        return None
    slicer = _SlicerColors(source="PrusaSlicer", filaments=filaments)
    for obj in ET.fromstring(model_config).iter("object"):
        object_id = obj.get("id", "")
        default = _metadata_int(obj, "extruder", kind="object") or 1
        slicer.objects[object_id] = default
        volumes: list[_Volume] = []
        for volume in obj.iter("volume"):
            chosen = _metadata_int(volume, "extruder", kind="volume") or default
            volume_type = _metadata(volume, "volume_type", kind="volume")
            modifier = _metadata(volume, "modifier", kind="volume") == "1"
            volumes.append(
                _Volume(
                    first=int(volume.get("firstid", "0")),
                    last=int(volume.get("lastid", "-1")),
                    extruder=chosen,
                    printable=not modifier and volume_type in (None, _PRUSA_MODEL_PART),
                )
            )
        if volumes:
            slicer.volumes[object_id] = volumes
    return slicer


def _metadata(element: ET.Element, key: str, *, kind: str | None = None) -> str | None:
    """Value of a direct ``<metadata key=... value=...>`` child."""
    for child in element.findall("metadata"):
        if child.get("key") == key and (kind is None or child.get("type") == kind):
            return child.get("value")
    return None


def _metadata_int(
    element: ET.Element, key: str, *, kind: str | None = None
) -> int | None:
    value = _metadata(element, key, kind=kind)
    try:
        return None if value is None else int(value)
    except ValueError:
        return None


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
