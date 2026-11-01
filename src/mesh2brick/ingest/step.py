# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""STEP via cascadio (OpenCASCADE), from the optional ``step`` extra (ADR 0007).

cascadio reads the STEP file with OpenCASCADE's XDE reader (assemblies,
names, colours), tessellates it and returns a binary glTF, which trimesh
loads. OpenCASCADE works in millimetres internally, so the tessellation
tolerance ``input.step_tolerance_mm`` is in millimetres whatever unit the file
uses. glTF stores metres; we scale back to millimetres.

Colours: STEP surface colours become glTF material colours (linear light);
:func:`mesh2brick.ingest.colors.from_visual` converts them back to sRGB.
Every solid becomes one part (``input.multi_body`` decides about several).
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Final

import numpy as np
import trimesh

from mesh2brick.ingest.base import IngestError, RawModel

if TYPE_CHECKING:
    from pathlib import Path

    from mesh2brick.config import InputConfig

ANGULAR_TOLERANCE_RAD: Final = 0.5
"""Max angle between neighbouring triangles on curved faces (OpenCASCADE's
default); the linear tolerance is usually the stricter limit."""
DEFAULT_TOLERANCE_MM: Final = 0.05
_TO_MM: Final = np.diag([1000.0, 1000.0, 1000.0, 1.0])
"""glTF metres -> millimetres."""
INSTALL_HINT: Final = (
    "STEP import needs the optional 'step' extra: "
    "`uv sync --extra step` (or `pip install 'mesh2brick[step]'`)"
)


def step_available() -> bool:
    """Whether the optional STEP reader (cascadio) is installed."""
    try:
        import cascadio  # noqa: F401, PLC0415 - optional dependency probe
    except ImportError:
        return False
    return True


class StepLoader:
    """Loader for ``.step`` and ``.stp`` files."""

    suffixes: frozenset[str] = frozenset({".step", ".stp"})

    def load(self, path: Path, config: InputConfig | None = None) -> RawModel:
        """Tessellate every solid of the file (millimetres).

        Raises:
            IngestError: if cascadio is missing or the file has no shapes.
        """
        try:
            import cascadio  # noqa: PLC0415 - optional dependency
        except ImportError as error:
            raise IngestError(INSTALL_HINT) from error
        tolerance = DEFAULT_TOLERANCE_MM if config is None else config.step_tolerance_mm
        glb = cascadio.load(
            path.read_bytes(),
            file_type="step",
            tol_linear=tolerance,
            tol_angular=ANGULAR_TOLERANCE_RAD,
            tol_relative=False,
            merge_primitives=True,
            use_parallel=True,
        )
        if not glb:
            msg = f"cannot read STEP file {path.name} (no shapes found)"
            raise IngestError(msg)
        scene = trimesh.load(io.BytesIO(glb), file_type="glb", process=False)
        geometries = scene.dump() if isinstance(scene, trimesh.Scene) else [scene]
        parts: list[trimesh.Trimesh] = []
        names: list[str] = []
        for index, geometry in enumerate(geometries):
            if isinstance(geometry, trimesh.Trimesh) and len(geometry.faces):
                geometry.apply_transform(_TO_MM)
                parts.append(geometry)
                names.append(str(geometry.metadata.get("name", f"solid {index + 1}")))
        if not parts:
            msg = f"STEP file {path.name} contains no solids or surfaces"
            raise IngestError(msg)
        return RawModel(
            parts=tuple(parts),
            names=tuple(names),
            notes=(f"STEP tessellated with {tolerance:g} mm tolerance",),
        )
