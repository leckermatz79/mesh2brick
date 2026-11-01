# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Bring a loaded model into the canonical frame and repair what we can.

Canonical frame: millimetres, the configured up axis mapped to +Z (a proper
rotation, never a mirror), outward-facing normals. Translation is irrelevant
because voxelization derives its lattice from the bounds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import trimesh

from mesh2brick.ingest.base import FaceColors, IngestError, MeshModel, RawModel
from mesh2brick.ingest.colors import (
    concat,
    corner_permutation,
    extend,
    from_visual,
    permute_corners,
    take,
)

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from mesh2brick.config import Axis, InputConfig

# Rotations taking the named axis onto +Z (det = +1).
UP_ROTATIONS: Final[dict[str, tuple[tuple[int, int, int], ...]]] = {
    "z": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "-z": ((1, 0, 0), (0, -1, 0), (0, 0, -1)),
    "y": ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
    "-y": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "x": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    "-x": ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),
}


def normalize(raw: RawModel, config: InputConfig, *, source: Path) -> MeshModel:
    """Merge the parts, orient, repair and report watertightness.

    Raises:
        IngestError: for several parts when ``input.multi_body`` is ``error``.
    """
    if config.multi_body == "error" and len(raw.parts) > 1:
        msg = (
            f"{source.name} has {len(raw.parts)} bodies ({', '.join(raw.names[:5])}"
            f"{', ...' if len(raw.parts) > 5 else ''}); set input.multi_body: union "  # noqa: PLR2004
            "to merge them"
        )
        raise IngestError(msg)
    warnings = list(raw.notes)
    face_part = np.concatenate(
        [np.full(len(p.faces), i, dtype=np.int32) for i, p in enumerate(raw.parts)]
    )
    part_colors = (
        list(raw.colors) if raw.colors else [from_visual(p) for p in raw.parts]
    )
    colors = concat(part_colors, [len(p.faces) for p in raw.parts])
    mesh = _merge_geometry(raw.parts)
    mesh.apply_transform(_homogeneous(up_rotation(config.up_axis)))
    if config.auto_orient:
        mesh.apply_transform(_homogeneous(stable_rest_rotation(mesh)))
        warnings.append("auto_orient: model rests on its most stable side")
    face_part, colors, repair_notes = _repair(mesh, face_part, colors)
    face_part.setflags(write=False)
    warnings.extend(repair_notes)
    watertight = bool(mesh.is_watertight) or parts_are_closed(
        np.asarray(mesh.faces), face_part
    )
    if not watertight:
        warnings.append(
            "mesh is not watertight even after repair; falling back to surface "
            "voxelization (thin walls may be lost, enclosed volume is filled)"
        )
    return MeshModel(
        mesh=mesh,
        source=source,
        part_names=raw.names,
        watertight=watertight,
        warnings=tuple(warnings),
        face_part=face_part,
        colors=colors,
    )


def up_rotation(axis: Axis) -> NDArray[np.float64]:
    """3x3 rotation mapping the model's ``axis`` onto +Z."""
    return np.asarray(UP_ROTATIONS[axis], dtype=np.float64)


def stable_rest_rotation(mesh: trimesh.Trimesh) -> NDArray[np.float64]:
    """Rotation that rests the model on its most stable convex-hull face.

    "Most stable" = the face closest to the centre of mass, which gives the
    lowest centre of gravity. For a convex hull the foot point of that face
    always lies inside it, so the pose really stands.
    """
    hull = mesh.convex_hull
    centre = mesh.center_mass if mesh.is_volume else mesh.centroid
    normals = np.asarray(hull.face_normals)
    distance = np.einsum("ij,ij->i", normals, np.asarray(hull.triangles[:, 0]) - centre)
    down = normals[int(np.argmin(distance))]
    return _rotation_between(down, np.array([0.0, 0.0, -1.0]))


def _rotation_between(
    a: NDArray[np.float64], b: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Smallest rotation turning unit vector ``a`` onto unit vector ``b``."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    cross = np.cross(a, b)
    dot = float(np.dot(a, b))
    if np.linalg.norm(cross) < 1e-12:  # noqa: PLR2004 - numerical zero
        if dot > 0:
            return np.eye(3)
        # Opposite: rotate 180 degrees about any axis perpendicular to a.
        helper = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])  # noqa: PLR2004
        axis = np.cross(a, helper)
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    skew = np.array(
        [[0, -cross[2], cross[1]], [cross[2], 0, -cross[0]], [-cross[1], cross[0], 0]]
    )
    result: NDArray[np.float64] = np.eye(3) + skew + skew @ skew / (1 + dot)
    return result


def _homogeneous(rotation: NDArray[np.float64]) -> NDArray[np.float64]:
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    return matrix


def parts_are_closed(faces: NDArray[np.int64], face_part: NDArray[np.int32]) -> bool:
    """Whether every part on its own is closed (each edge used by two faces).

    Touching bodies share vertices after merging, so their common edges have
    four faces and the merged mesh is not "watertight". Each body is still a
    closed surface, which is all the winding-number union needs. Faces that
    belong to no part (hole filling) make the answer ``False``.
    """
    if len(faces) == 0 or (face_part < 0).any() or len(face_part) != len(faces):
        return False
    edges = np.sort(faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1)
    owner = np.repeat(face_part, 3).astype(np.int64)
    vertices = int(faces.max()) + 1
    if (int(owner.max()) + 1) * vertices * vertices < np.iinfo(np.int64).max:
        # One int64 key per (part, edge): 1-D unique is several times faster.
        keys = (owner * vertices + edges[:, 0]) * vertices + edges[:, 1]
        _, counts = np.unique(keys, return_counts=True)
    else:  # pragma: no cover - needs > ~3 billion vertex pairs per part
        stacked = np.stack([owner, edges[:, 0], edges[:, 1]], axis=1)
        _, counts = np.unique(stacked, axis=0, return_counts=True)
    return bool((counts == 2).all())  # noqa: PLR2004 - two faces per edge


def _merge_geometry(parts: tuple[trimesh.Trimesh, ...]) -> trimesh.Trimesh:
    """One mesh from all parts, geometry only (visuals are tracked separately).

    Dropping the visuals lets vertices at UV seams merge (they would otherwise
    stay split and leave the mesh open) and avoids texture-atlas packing.
    """
    vertices = [np.asarray(p.vertices, dtype=np.float64) for p in parts]
    offsets = np.cumsum([0] + [len(v) for v in vertices[:-1]])
    faces = [
        np.asarray(p.faces, dtype=np.int64) + o
        for p, o in zip(parts, offsets, strict=True)
    ]
    return trimesh.Trimesh(
        vertices=np.concatenate(vertices), faces=np.concatenate(faces), process=False
    )


def _repair(
    mesh: trimesh.Trimesh,
    face_part: NDArray[np.int32],
    colors: FaceColors | None,
) -> tuple[NDArray[np.int32], FaceColors | None, list[str]]:
    """Merge vertices, drop degenerate faces, orient normals, close small holes.

    ``face_part`` and ``colors`` are updated to stay aligned with the faces.
    """
    notes: list[str] = []
    mesh.merge_vertices()
    keep = np.asarray(mesh.nondegenerate_faces())
    if not keep.all():
        notes.append(f"removed {int((~keep).sum())} degenerate faces")
        mesh.update_faces(keep)
        face_part = face_part[keep]
        colors = None if colors is None else take(colors, keep)
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight:
        before = len(mesh.faces)
        trimesh.repair.fill_holes(mesh)
        added = len(mesh.faces) - before
        if added:
            notes.append(f"filled holes with {added} faces")
            face_part = np.concatenate([face_part, np.full(added, -1, dtype=np.int32)])
            colors = None if colors is None else extend(colors, added)
    corners = np.array(mesh.faces, dtype=np.int64)
    trimesh.repair.fix_normals(mesh, multibody=True)  # type: ignore[no-untyped-call]
    if colors is not None and (colors.vertex is not None or colors.uv is not None):
        perm = corner_permutation(corners, np.asarray(mesh.faces, dtype=np.int64))
        if perm is not None:
            colors = permute_corners(colors, perm)
    return face_part, colors, notes
