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

from mesh2brick.ingest.base import MeshModel, RawModel

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
    """Merge the parts, orient, repair and report watertightness."""
    warnings = list(raw.notes)
    face_part = np.concatenate(
        [np.full(len(p.faces), i, dtype=np.int32) for i, p in enumerate(raw.parts)]
    )
    mesh = trimesh.util.concatenate(list(raw.parts))
    if not isinstance(mesh, trimesh.Trimesh):  # pragma: no cover - defensive
        msg = "could not merge the model's parts into one mesh"
        raise TypeError(msg)
    mesh.apply_transform(_homogeneous(up_rotation(config.up_axis)))
    if config.auto_orient:
        mesh.apply_transform(_homogeneous(stable_rest_rotation(mesh)))
        warnings.append("auto_orient: model rests on its most stable side")
    face_part, repair_notes = _repair(mesh, face_part)
    face_part.setflags(write=False)
    warnings.extend(repair_notes)
    watertight = bool(mesh.is_watertight)
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


def _repair(
    mesh: trimesh.Trimesh, face_part: NDArray[np.int32]
) -> tuple[NDArray[np.int32], list[str]]:
    """Merge vertices, drop degenerate faces, orient normals, close small holes."""
    notes: list[str] = []
    mesh.merge_vertices()
    keep = np.asarray(mesh.nondegenerate_faces())
    if not keep.all():
        notes.append(f"removed {int((~keep).sum())} degenerate faces")
        mesh.update_faces(keep)
        face_part = face_part[keep]
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight:
        before = len(mesh.faces)
        trimesh.repair.fill_holes(mesh)
        added = len(mesh.faces) - before
        if added:
            notes.append(f"filled holes with {added} faces")
            face_part = np.concatenate([face_part, np.full(added, -1, dtype=np.int32)])
    trimesh.repair.fix_normals(mesh, multibody=True)  # type: ignore[no-untyped-call]
    return face_part, notes
