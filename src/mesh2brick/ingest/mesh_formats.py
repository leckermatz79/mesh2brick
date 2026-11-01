# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""STL, OBJ and PLY via trimesh.

These formats carry no reliable unit, so millimetres are assumed (the 3D
printing convention). With ``input.scale_mode: studs`` (the default) the unit
does not matter because the model is scaled to ``target_studs`` anyway.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import trimesh

from mesh2brick.ingest.base import IngestError, RawModel

if TYPE_CHECKING:
    from pathlib import Path


class TrimeshLoader:
    """Loader for ``.stl``, ``.obj`` and ``.ply``."""

    suffixes: frozenset[str] = frozenset({".stl", ".obj", ".ply"})

    def load(self, path: Path) -> RawModel:
        """Read all geometry of the file as one or more parts (millimetres assumed).

        Raises:
            IngestError: if trimesh cannot read the file or it has no faces.
        """
        try:
            loaded = trimesh.load(path, process=True)
        except Exception as error:  # trimesh raises many unrelated types
            msg = f"cannot read {path.name}: {error}"
            raise IngestError(msg) from error
        parts: list[trimesh.Trimesh]
        names: list[str]
        if isinstance(loaded, trimesh.Scene):
            parts, names = [], []
            # dump() applies the scene-graph transforms to every instance.
            for index, geometry in enumerate(loaded.dump()):
                if isinstance(geometry, trimesh.Trimesh) and len(geometry.faces):
                    parts.append(geometry)
                    names.append(str(geometry.metadata.get("name", f"part {index}")))
        elif isinstance(loaded, trimesh.Trimesh):
            parts, names = [loaded], [path.stem]
        else:
            parts, names = [], []
        if not parts or not any(len(p.faces) for p in parts):
            msg = f"{path.name} contains no triangle faces (point cloud or empty?)"
            raise IngestError(msg)
        return RawModel(
            parts=tuple(parts),
            names=tuple(names),
            notes=(f"{path.suffix.lower()} has no units; assuming millimetres",),
        )
