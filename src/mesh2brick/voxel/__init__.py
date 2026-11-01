# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Voxel stage: mesh -> coloured stud-raster grid.

Phase 0 ships the :class:`~mesh2brick.voxel.grid.VoxelGrid` data type.
Voxelization (``voxelize.py``), colour assignment (``color.py``) and file I/O
(``io.py``) follow in Phase 1.
"""

from mesh2brick.voxel.grid import EMPTY, VoxelGrid

__all__ = ["EMPTY", "VoxelGrid"]
