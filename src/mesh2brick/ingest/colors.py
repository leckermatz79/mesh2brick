# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Colour sources of input meshes, kept aligned with the faces.

Loaders hand over trimesh parts. Their colours live in trimesh "visuals":

* material colours (OBJ ``Kd``, glTF ``baseColorFactor``) -> ``cad``,
* vertex or face colour attributes (PLY, OBJ ``v x y z r g b``) -> ``vertex``,
* image textures with UV coordinates (OBJ ``map_Kd``, glTF) -> ``texture``.

:func:`from_visual` turns them into :class:`FaceColors` arrays with one entry
per face. Those survive merging and mesh repair (:func:`concat`, :func:`take`,
:func:`extend`, :func:`permute_corners`), so the colours still match the faces
when the voxelizer looks them up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import trimesh
from PIL import Image

from mesh2brick.ingest.base import FaceColors

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

MAX_TEXTURE_SIZE: Final = 2048
"""Longer texture sides are scaled down; cells are far coarser than that."""
_DEFAULT_GREY: Final = (102, 102, 102)
"""trimesh's placeholder colour for meshes without a material."""
_HEX_DIGITS: Final = frozenset("0123456789abcdefABCDEF")


# ----------------------------------------------------------------- colour maths
def srgb_to_linear(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Convert sRGB (0..1) to linear light (0..1), IEC 61966-2-1."""
    result: NDArray[np.float64] = np.where(
        values <= 0.04045,  # noqa: PLR2004 - standard constant
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )
    return result


def linear_to_srgb(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Convert linear light (0..1) to sRGB (0..1), IEC 61966-2-1."""
    values = np.clip(values, 0.0, 1.0)
    result: NDArray[np.float64] = np.where(
        values <= 0.0031308,  # noqa: PLR2004 - standard constant
        values * 12.92,
        1.055 * values ** (1 / 2.4) - 0.055,
    )
    return result


def to_bytes(values: NDArray[np.float64]) -> NDArray[np.uint8]:
    """0..1 floats to 0..255 bytes (rounded)."""
    return np.clip(np.rint(values * 255.0), 0, 255).astype(np.uint8)


def parse_hex_color(text: str) -> tuple[int, int, int] | None:
    """Parse ``#RRGGBB`` or ``#RRGGBBAA`` (3MF, slicers); ``None`` if invalid."""
    digits = text.strip().removeprefix("#")
    if len(digits) not in (6, 8) or not set(digits) <= _HEX_DIGITS:
        return None
    return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))


# ----------------------------------------------------------------- extraction
def from_visual(mesh: trimesh.Trimesh) -> FaceColors | None:
    """The colour sources of one trimesh part (``None`` if it has none)."""
    faces = np.asarray(mesh.faces)
    visual = mesh.visual
    count = len(faces)
    if isinstance(visual, trimesh.visual.ColorVisuals):
        corners = _attribute_corners(visual, faces)
        if corners is None:
            return None
        return FaceColors(
            cad=np.zeros((count, 3), dtype=np.uint8),
            cad_mask=np.zeros(count, dtype=bool),
            vertex=corners,
            vertex_mask=np.ones(count, dtype=bool),
        )
    if isinstance(visual, trimesh.visual.TextureVisuals):
        material = visual.material
        image, tint = _material_image(material)
        uv = None if visual.uv is None else np.asarray(visual.uv, dtype=np.float32)
        if image is not None and uv is not None and len(uv) == len(mesh.vertices):
            return FaceColors(
                cad=np.zeros((count, 3), dtype=np.uint8),
                cad_mask=np.zeros(count, dtype=bool),
                uv=uv[faces],
                texture=np.zeros(count, dtype=np.int32),
                textures=(_tinted(image, tint),),
            )
        rgb = _material_color(material)
        if rgb is None:
            return None
        return FaceColors.uniform(rgb, count)
    return None


def _attribute_corners(
    visual: trimesh.visual.ColorVisuals, faces: NDArray[np.int64]
) -> NDArray[np.uint8] | None:
    """Per-corner RGB of a ColorVisuals, or ``None`` when no colour was set."""
    match visual.kind:
        case "vertex":
            colors = np.asarray(visual.vertex_colors)[:, :3]
            return np.ascontiguousarray(colors[faces], dtype=np.uint8)
        case "face":
            colors = np.asarray(visual.face_colors)[:, :3].astype(np.uint8)
            return np.repeat(colors[:, None, :], 3, axis=1)
        case _:
            return None


def _material_image(
    material: object,
) -> tuple[Image.Image | None, NDArray[np.float64] | None]:
    """Texture image and linear tint (glTF ``baseColorFactor``) of a material.

    OBJ ``Kd`` is ignored for textured materials: exporters write placeholder
    values there (Blender: 0.8 grey) that viewers do not apply to textures.
    """
    if isinstance(material, trimesh.visual.material.PBRMaterial):
        factor = material.baseColorFactor
        # trimesh stores the (linear) factor as 0..255 bytes.
        tint = None if factor is None else np.asarray(factor, np.float64)[:3] / 255.0
        return material.baseColorTexture, tint
    if isinstance(material, trimesh.visual.material.SimpleMaterial):
        return material.image, None
    return None, None


def _material_color(material: object) -> tuple[int, int, int] | None:
    """Flat sRGB colour of an untextured material (``None`` for placeholders)."""
    if isinstance(material, trimesh.visual.material.PBRMaterial):
        factor = material.baseColorFactor
        if factor is None:
            return None
        linear = np.asarray(factor, dtype=np.float64)[:3] / 255.0
        r, g, b = (int(v) for v in to_bytes(linear_to_srgb(linear)))
        return (r, g, b)
    if isinstance(material, trimesh.visual.material.SimpleMaterial):
        r, g, b = (int(v) for v in np.asarray(material.diffuse)[:3])
        if (r, g, b) == _DEFAULT_GREY:  # trimesh's stand-in for "no material"
            return None
        return (r, g, b)
    return None


def _tinted(image: Image.Image, tint: NDArray[np.float64] | None) -> NDArray[np.uint8]:
    """RGB array of ``image`` (at most MAX_TEXTURE_SIZE), multiplied by ``tint``."""
    rgb = image.convert("RGB")
    if max(rgb.size) > MAX_TEXTURE_SIZE:
        rgb.thumbnail((MAX_TEXTURE_SIZE, MAX_TEXTURE_SIZE), Image.Resampling.BOX)
    pixels = np.asarray(rgb, dtype=np.uint8)
    if tint is None or np.allclose(tint, 1.0):
        return np.ascontiguousarray(pixels)
    linear = srgb_to_linear(pixels / 255.0) * tint
    return to_bytes(linear_to_srgb(linear))


# ----------------------------------------------------------------- bookkeeping
def concat(
    colors: Sequence[FaceColors | None], face_counts: Sequence[int]
) -> FaceColors | None:
    """Colours of merged parts (``None`` entries mean "no colour")."""
    if all(c is None for c in colors):
        return None
    parts = [
        c if c is not None else _blank(n)
        for c, n in zip(colors, face_counts, strict=True)
    ]
    any_vertex = any(p.vertex is not None for p in parts)
    any_uv = any(p.uv is not None for p in parts)
    vertex = vertex_mask = uv = texture = None
    if any_vertex:
        vertex = np.concatenate(
            [
                p.vertex
                if p.vertex is not None
                else np.zeros((p.face_count, 3, 3), np.uint8)
                for p in parts
            ]
        )
        vertex_mask = np.concatenate([p.mask("vertex") for p in parts])
    textures: list[NDArray[np.uint8]] = []
    if any_uv:
        uvs, indices = [], []
        for p in parts:
            if p.uv is None or p.texture is None:
                uvs.append(np.zeros((p.face_count, 3, 2), np.float32))
                indices.append(np.full(p.face_count, -1, np.int32))
                continue
            uvs.append(p.uv)
            indices.append(np.where(p.texture >= 0, p.texture + len(textures), -1))
            textures.extend(p.textures)
        uv = np.concatenate(uvs).astype(np.float32)
        texture = np.concatenate(indices).astype(np.int32)
    return FaceColors(
        cad=np.concatenate([p.cad for p in parts]),
        cad_mask=np.concatenate([p.cad_mask for p in parts]),
        vertex=vertex,
        vertex_mask=vertex_mask,
        uv=uv,
        texture=texture,
        textures=tuple(textures),
    )


def take(colors: FaceColors, keep: NDArray[np.bool_]) -> FaceColors:
    """Colours of the faces where ``keep`` is set (in order)."""
    return FaceColors(
        cad=colors.cad[keep],
        cad_mask=colors.cad_mask[keep],
        vertex=None if colors.vertex is None else colors.vertex[keep],
        vertex_mask=None if colors.vertex_mask is None else colors.vertex_mask[keep],
        uv=None if colors.uv is None else colors.uv[keep],
        texture=None if colors.texture is None else colors.texture[keep],
        textures=colors.textures,
    )


def extend(colors: FaceColors, added: int) -> FaceColors:
    """Append ``added`` faces without colour (e.g. from hole filling)."""
    blank = _blank(added)
    return FaceColors(
        cad=np.concatenate([colors.cad, blank.cad]),
        cad_mask=np.concatenate([colors.cad_mask, blank.cad_mask]),
        vertex=None
        if colors.vertex is None
        else np.concatenate([colors.vertex, np.zeros((added, 3, 3), np.uint8)]),
        vertex_mask=None
        if colors.vertex_mask is None
        else np.concatenate([colors.vertex_mask, np.zeros(added, bool)]),
        uv=None
        if colors.uv is None
        else np.concatenate([colors.uv, np.zeros((added, 3, 2), np.float32)]),
        texture=None
        if colors.texture is None
        else np.concatenate([colors.texture, np.full(added, -1, np.int32)]),
        textures=colors.textures,
    )


def corner_permutation(
    before: NDArray[np.int64], after: NDArray[np.int64]
) -> NDArray[np.int64] | None:
    """Where each corner of reordered faces (winding flips) came from.

    ``after[f, k] == before[f, perm[f, k]]``. Returns ``None`` if nothing
    moved. Faces must not repeat a vertex.
    """
    if before.shape != after.shape:
        msg = "face count changed; cannot track corner order"
        raise ValueError(msg)
    if np.array_equal(before, after):
        return None
    match = before[:, None, :] == after[:, :, None]
    perm: NDArray[np.int64] = np.argmax(match, axis=2)
    return perm


def permute_corners(colors: FaceColors, perm: NDArray[np.int64]) -> FaceColors:
    """Reorder the per-corner arrays like the faces' corners (see above)."""
    rows = np.arange(len(perm))[:, None]
    return FaceColors(
        cad=colors.cad,
        cad_mask=colors.cad_mask,
        vertex=None if colors.vertex is None else colors.vertex[rows, perm],
        vertex_mask=colors.vertex_mask,
        uv=None if colors.uv is None else colors.uv[rows, perm],
        texture=colors.texture,
        textures=colors.textures,
    )


def _blank(faces: int) -> FaceColors:
    return FaceColors(
        cad=np.zeros((faces, 3), dtype=np.uint8),
        cad_mask=np.zeros(faces, dtype=bool),
    )
