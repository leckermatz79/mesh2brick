# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""glTF 2.0 (``.glb``, ``.gltf``) via trimesh, with the spec's conventions.

glTF fixes what STL and OBJ leave open, and this reader applies it:

* **+Y is up** and lengths are metres. Parts are rotated to +Z up and scaled
  to millimetres, so ``input.up_axis`` stays ``z`` for glTF files.
* **Colours are linear light.** ``baseColorFactor`` and the vertex colour
  attribute ``COLOR_0`` multiply each other; the result is converted to sRGB.
  trimesh hands ``COLOR_0`` over unconverted (and drops it as a colour when
  the primitive also has a material), so the vertex colours are read here.
  trimesh 5.2 also wraps 16-bit colours (Blender's default) modulo 256 when
  it turns them into bytes, so :func:`load_scene` rescales them to 0..1
  first and keeps the exact values as the vertex attribute ``color``
  (docs/UPSTREAM.md #14).
* Every node with geometry becomes one part, named after the node (Blender
  writes object names there), scene-graph transforms applied.

:mod:`mesh2brick.ingest.blender` reuses :func:`read_gltf` for ``.blend``
files, which Blender exports to glTF first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import trimesh

from mesh2brick.ingest.base import FaceColors, IngestError, RawModel
from mesh2brick.ingest.colors import from_visual, linear_to_srgb, to_bytes

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from mesh2brick.config import InputConfig

MM_PER_METRE: Final = 1000.0
Y_UP_TO_Z_UP: Final = np.array(
    [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0, 0, 0, 1]]
)
"""Rotation (x, y, z) -> (x, -z, y): glTF's +Y up onto +Z up, +Z front onto -Y."""


class GltfLoader:
    """Loader for ``.glb`` and ``.gltf`` (external buffers next to the file)."""

    suffixes: frozenset[str] = frozenset({".glb", ".gltf"})

    def load(
        self,
        path: Path,
        config: InputConfig | None = None,  # noqa: ARG002 - no options yet
    ) -> RawModel:
        """Read every mesh node of the default scene (millimetres, z up).

        Raises:
            IngestError: if trimesh cannot read the file or it has no faces.
        """
        return read_gltf(path)


def read_gltf(
    path: Path, *, mm_per_unit: float = MM_PER_METRE, notes: tuple[str, ...] = ()
) -> RawModel:
    """Parts of a glTF file in millimetres with +Z up and their colours.

    Args:
        path: the ``.glb``/``.gltf`` file.
        mm_per_unit: millimetres per glTF unit (the spec says metres; Blender
            writes its scene units unchanged, see the ``.blend`` loader).
        notes: remarks to pass on with the result.

    Raises:
        IngestError: if trimesh cannot read the file or it has no faces.
    """
    try:
        scene = load_scene(path)
    except Exception as error:  # trimesh raises many unrelated types
        msg = f"cannot read {path.name}: {error}"
        raise IngestError(msg) from error
    to_frame = Y_UP_TO_Z_UP @ np.diag([mm_per_unit, mm_per_unit, mm_per_unit, 1.0])
    parts: list[trimesh.Trimesh] = []
    names: list[str] = []
    colors: list[FaceColors | None] = []
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node]
        geometry = scene.geometry.get(geometry_name)
        if not isinstance(geometry, trimesh.Trimesh) or not len(geometry.faces):
            continue
        # Colours first: Trimesh.copy() drops vertex attributes such as COLOR_0.
        colors.append(gltf_colors(geometry))
        part = geometry.copy()
        part.apply_transform(to_frame @ np.asarray(transform, dtype=np.float64))
        parts.append(part)
        names.append(str(node))
    if not parts:
        msg = f"{path.name} contains no triangle meshes"
        raise IngestError(msg)
    return RawModel(
        parts=tuple(parts),
        names=tuple(names),
        notes=notes,
        colors=tuple(colors) if any(c is not None for c in colors) else (),
    )


def load_scene(path: Path) -> trimesh.Scene:
    """The glTF file as a trimesh scene, with exact vertex colours.

    Reads the file with trimesh's glTF parser, turns wide integer ``COLOR_0``
    values into 0..1 floats (see the module docs) and builds the scene from
    the result.
    """
    parser = (
        trimesh.exchange.gltf.load_glb
        if path.suffix.lower() == ".glb"
        else trimesh.exchange.gltf.load_gltf
    )
    with path.open("rb") as handle:
        kwargs = parser(
            handle,
            resolver=trimesh.resolvers.FilePathResolver(str(path)),
            process=False,
        )
    for geometry in kwargs.get("geometry", {}).values():
        if isinstance(geometry, dict):
            _exact_vertex_colors(geometry)
    scene = trimesh.load(kwargs, force="scene")
    if not isinstance(scene, trimesh.Scene):  # pragma: no cover - force="scene"
        msg = "not a glTF scene"
        raise TypeError(msg)
    return scene


def _exact_vertex_colors(geometry: dict[str, object]) -> None:
    """Integer vertex colours -> 0..1 floats, kept as attribute ``color``."""
    raw = geometry.get("vertex_colors")
    if raw is None:
        return
    values = np.asarray(raw)
    if values.dtype.kind in "iu":
        values = values.astype(np.float64) / float(np.iinfo(str(values.dtype)).max)
    elif values.dtype.kind != "f":  # pragma: no cover - not a colour array
        return
    geometry["vertex_colors"] = values
    attributes = geometry.setdefault("vertex_attributes", {})
    if isinstance(attributes, dict):
        attributes["color"] = values


def gltf_colors(mesh: trimesh.Trimesh) -> FaceColors | None:
    """Colour sources of one glTF primitive (sRGB), ``None`` if it has none.

    Material colours and textures are read like any trimesh visual. Vertex
    colours (``COLOR_0``) are multiplied by ``baseColorFactor`` in linear
    light and become the ``vertex`` source.
    """
    base = from_visual(mesh)
    linear = linear_vertex_colors(mesh)
    if linear is None:
        return base
    factor = _base_factor(mesh.visual)
    srgb = to_bytes(linear_to_srgb(linear * factor))
    faces = np.asarray(mesh.faces, dtype=np.int64)
    count = len(faces)
    if base is None:
        return FaceColors(
            cad=np.zeros((count, 3), dtype=np.uint8),
            cad_mask=np.zeros(count, dtype=bool),
            vertex=np.ascontiguousarray(srgb[faces]),
            vertex_mask=np.ones(count, dtype=bool),
        )
    return FaceColors(
        cad=base.cad,
        cad_mask=base.cad_mask,
        vertex=np.ascontiguousarray(srgb[faces]),
        vertex_mask=np.ones(count, dtype=bool),
        uv=base.uv,
        texture=base.texture,
        textures=base.textures,
    )


def linear_vertex_colors(mesh: trimesh.Trimesh) -> NDArray[np.float64] | None:
    """``COLOR_0`` of a glTF primitive as linear RGB in 0..1, or ``None``.

    trimesh keeps the attribute's raw (linear) values in one of three places:
    the mesh attribute ``color`` (written by :func:`load_scene`), the texture
    visual's attribute ``color`` (primitives with a material, in the file's
    own type: uint8, uint16 or float), or ``vertex_colors`` bytes.
    """
    visual = mesh.visual
    raw: NDArray[np.generic] | None = None
    # A dict on the mesh, a trimesh DataStore on texture visuals.
    stores: tuple[object, ...] = (
        mesh.vertex_attributes,
        getattr(visual, "vertex_attributes", None),
    )
    for attributes in stores:
        getter = getattr(attributes, "get", None)
        value = getter("color") if callable(getter) else None
        if value is not None:
            raw = np.asarray(value)
            break
    if (
        raw is None
        and isinstance(visual, trimesh.visual.ColorVisuals)
        and visual.kind == "vertex"
    ):
        raw = np.asarray(visual.vertex_colors)
    vertices = len(mesh.vertices)
    if raw is None or raw.ndim != 2 or len(raw) != vertices or raw.shape[1] < 3:  # noqa: PLR2004
        return None
    values = raw[:, :3]
    if np.issubdtype(values.dtype, np.integer):
        scale = float(np.iinfo(str(values.dtype)).max)
        return values.astype(np.float64) / scale
    return np.clip(values.astype(np.float64), 0.0, 1.0)


def _base_factor(visual: object) -> NDArray[np.float64]:
    """Linear ``baseColorFactor`` RGB of the primitive (white if unset)."""
    material = getattr(visual, "material", None)
    if isinstance(material, trimesh.visual.material.PBRMaterial):
        factor = material.baseColorFactor
        if factor is not None:
            # trimesh stores the (linear) factor as 0..255 bytes.
            return np.asarray(factor, dtype=np.float64)[:3] / 255.0
    return np.ones(3)
