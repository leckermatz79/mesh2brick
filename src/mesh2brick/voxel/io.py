# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Voxel grid files.

* ``.npz`` - mesh2brick's own lossless format (occupancy, colours, cell
  size, origin and, since 2.0, the flat tops; older files read without
  them). Use it to hand a grid from ``voxelize`` to ``place``.
* ``.npy`` - a single ``int16`` array of LDraw colour codes, ``-1`` = empty,
  axes ``(x, y, z)`` with z up. This is exactly what legolization's
  ``VoxelGrid.from_npy`` reads (one voxel = one brick by default).
* ``.vox`` - MagicaVoxel (version 150: ``SIZE``, ``XYZI``, ``RGBA`` chunks),
  z up, for viewing grids in MagicaVoxel or feeding legolization directly.
  Colours are stored as RGB; legolization maps them back to the nearest solid
  LDraw colour, which round-trips for every solid palette colour.

Reading ``.npy``/``.vox`` goes through the backend (it owns the palette).
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any, Final

import numpy as np

from mesh2brick.voxel.grid import EMPTY, VoxelGrid

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

NPZ_SCHEMA: Final = 1
VOX_MAX_SIZE: Final = 256
VOX_MAX_COLORS: Final = 255
_VOX_VERSION: Final = 150


def save_npz(grid: VoxelGrid, path: Path) -> Path:
    """Write ``grid`` losslessly (compressed) and return ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray[Any, Any]] = {
        "schema": np.asarray(NPZ_SCHEMA, dtype=np.int32),
        "occupancy": grid.occupancy,
        "color": grid.color,
        "height_unit": np.asarray(grid.height_unit),
        "pitch_mm": np.asarray(grid.pitch_mm, dtype=np.float64),
        "origin_mm": np.asarray(grid.origin_mm, dtype=np.float64),
    }
    if grid.flat is not None:
        arrays["flat"] = grid.flat
    with path.open("wb") as handle:
        np.savez_compressed(handle, allow_pickle=False, **arrays)
    return path


def load_npz(path: Path) -> VoxelGrid:
    """Read a grid written by :func:`save_npz`.

    Raises:
        ValueError: on a foreign or newer file.
    """
    with np.load(path, allow_pickle=False) as data:
        if "schema" not in data or int(data["schema"]) != NPZ_SCHEMA:
            msg = f"{path.name} is not a mesh2brick grid (schema {NPZ_SCHEMA})"
            raise ValueError(msg)
        unit = str(data["height_unit"])
        if unit not in {"brick", "plate"}:
            msg = f"{path.name}: unknown height unit {unit!r}"
            raise ValueError(msg)
        origin = tuple(float(v) for v in data["origin_mm"])
        return VoxelGrid(
            occupancy=data["occupancy"].astype(bool),
            color=data["color"].astype(np.int32),
            height_unit="brick" if unit == "brick" else "plate",
            pitch_mm=float(data["pitch_mm"]),
            origin_mm=(origin[0], origin[1], origin[2]),
            flat=data["flat"].astype(np.float32) if "flat" in data else None,
        )


def write_npy(grid: VoxelGrid, path: Path) -> Path:
    """Write the legolization-compatible code array and return ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, grid.to_codes())
    return path


def write_vox(
    grid: VoxelGrid,
    path: Path,
    rgb: Mapping[int, tuple[int, int, int]],
) -> Path:
    """Write a MagicaVoxel file (one voxel per cell) and return ``path``.

    Args:
        grid: the grid to write.
        path: target ``.vox`` file.
        rgb: display colour for every LDraw code used by the grid.

    Raises:
        ValueError: if the grid exceeds 256 cells per axis, uses more than 255
            colours, or a colour has no RGB entry.
    """
    if any(n > VOX_MAX_SIZE for n in grid.shape):
        msg = (
            f"MagicaVoxel allows at most {VOX_MAX_SIZE} cells per axis, "
            f"got {grid.shape}"
        )
        raise ValueError(msg)
    codes = grid.colors_used
    if len(codes) > VOX_MAX_COLORS:
        msg = f"MagicaVoxel allows at most {VOX_MAX_COLORS} colours, got {len(codes)}"
        raise ValueError(msg)
    if missing := [c for c in codes if c not in rgb]:
        msg = f"no RGB value for LDraw colours {missing}"
        raise ValueError(msg)
    index_of = {code: i + 1 for i, code in enumerate(codes)}
    xyz = np.argwhere(grid.occupancy)
    lookup = np.zeros(max(codes, default=0) + 1, dtype=np.uint8)
    for code, index in index_of.items():
        lookup[code] = index
    palette_index = lookup[grid.color[grid.occupancy]]
    voxels = np.column_stack([xyz.astype(np.uint8), palette_index]).astype(np.uint8)

    palette = np.zeros((256, 4), dtype=np.uint8)
    palette[:, 3] = 255
    for code, index in index_of.items():
        palette[index - 1, :3] = rgb[code]

    size = _chunk(b"SIZE", struct.pack("<iii", *grid.shape))
    xyzi = _chunk(b"XYZI", struct.pack("<i", len(voxels)) + voxels.tobytes())
    rgba = _chunk(b"RGBA", palette.tobytes())
    children = size + xyzi + rgba
    main = b"MAIN" + struct.pack("<ii", 0, len(children)) + children
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"VOX " + struct.pack("<i", _VOX_VERSION) + main)
    return path


def _chunk(chunk_id: bytes, content: bytes) -> bytes:
    return chunk_id + struct.pack("<ii", len(content), 0) + content


__all__ = ["EMPTY", "load_npz", "save_npz", "write_npy", "write_vox"]
