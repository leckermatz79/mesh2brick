# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""mesh2brick: turn 3D models into buildable LEGO-compatible models.

The package is organised as a pipeline of independent stages::

    ingest  ->  voxel  ->  backends (placement, stability, steps)  ->  export/render

Every stage works on immutable data types (:class:`~mesh2brick.voxel.grid.VoxelGrid`,
:class:`~mesh2brick.model.BrickModel`) and can be run on its own from the CLI.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mesh2brick")
except PackageNotFoundError:  # pragma: no cover - only when run from a raw checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
