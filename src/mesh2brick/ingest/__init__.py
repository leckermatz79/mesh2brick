# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Input formats -> normalised mesh (z up, millimetres, outward normals).

``load_model(path, settings.input)`` picks a loader by file suffix:
STL/OBJ/PLY via trimesh, 3MF via our own reader (core, materials, production
extension, slicer colours), glTF with its own conventions (Y up, metres,
linear colours) and STEP via cascadio (optional ``step`` extra).
``.blend`` (Phase 8) will register here too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mesh2brick.ingest.base import (
    IngestError,
    Loader,
    MeshModel,
    RawModel,
    loader_for,
    register,
    supported_suffixes,
)
from mesh2brick.ingest.gltf import GltfLoader
from mesh2brick.ingest.mesh_formats import TrimeshLoader
from mesh2brick.ingest.normalize import normalize
from mesh2brick.ingest.step import StepLoader
from mesh2brick.ingest.threemf import ThreeMFLoader

if TYPE_CHECKING:
    from pathlib import Path

    from mesh2brick.config import InputConfig

register(TrimeshLoader())
register(ThreeMFLoader())
register(StepLoader())
register(GltfLoader())


def load_model(path: Path, config: InputConfig) -> MeshModel:
    """Load ``path`` with the matching loader and normalise it.

    Raises:
        IngestError: for unsupported, unreadable or empty files.
    """
    if not path.is_file():
        msg = f"input file not found: {path}"
        raise IngestError(msg)
    raw = loader_for(path).load(path, config)
    return normalize(raw, config, source=path)


__all__ = [
    "IngestError",
    "Loader",
    "MeshModel",
    "RawModel",
    "load_model",
    "loader_for",
    "register",
    "supported_suffixes",
]
