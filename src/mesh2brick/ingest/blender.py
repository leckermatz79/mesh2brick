# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Blender ``.blend`` files via a headless Blender process (ADR 0014).

mesh2brick never imports ``bpy``. It starts the user's own Blender in
background mode and lets :mod:`mesh2brick.ingest.blender_export` write the
visible geometry of the active scene to a temporary binary glTF, which
:func:`mesh2brick.ingest.gltf.read_gltf` reads like any ``.glb`` file:

* modifiers, geometry nodes and collection instances are applied, curves and
  text become meshes, hidden objects, cameras and lights are left out;
* material colours, textures and colour attributes come along;
* the scene's unit scale is honoured (a "millimetre" scene stays in mm).

Blender runs with factory settings and with auto-run scripts disabled, so
neither the user's add-ons nor Python scripts stored in the file run. The
``.blend`` file is only read.

Blender is found via ``MESH2BRICK_BLENDER``, then ``blender`` on ``PATH``,
then the usual install locations (macOS, Windows, Linux snap/flatpak).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from mesh2brick.ingest.base import IngestError, RawModel
from mesh2brick.ingest.gltf import MM_PER_METRE, read_gltf

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mesh2brick.config import InputConfig

BLENDER_ENV: Final = "MESH2BRICK_BLENDER"
TIMEOUT_S: Final = 300.0
"""Longest time Blender may take to open and export a file."""
_OUTPUT_TAIL: Final = 12
"""Lines of Blender output quoted in error messages."""
INSTALL_HINT: Final = (
    ".blend import needs Blender (https://www.blender.org; tested with 4.0) on this "
    f"computer; set {BLENDER_ENV}=/path/to/blender if it is not found "
    "automatically, or export the model from Blender as .glb, .obj or .stl"
)


def candidate_paths(
    environ: Mapping[str, str] | None = None, platform: str | None = None
) -> list[Path]:
    """Where Blender may be installed, most specific first (not checked)."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    found: list[Path] = []
    if explicit := environ.get(BLENDER_ENV):
        found.append(Path(explicit).expanduser())
    if on_path := shutil.which("blender", path=environ.get("PATH")):
        found.append(Path(on_path))
    home = Path(environ.get("HOME", "~")).expanduser()
    if platform == "darwin":
        bundle = Path("Blender.app/Contents/MacOS/Blender")
        found += [Path("/Applications") / bundle, home / "Applications" / bundle]
    elif platform == "win32":
        for root in (environ.get("ProgramFiles"), environ.get("ProgramFiles(x86)")):
            if root:
                base = Path(root) / "Blender Foundation"
                found += sorted(base.glob("Blender*/blender.exe"), reverse=True)
    else:
        found += [
            Path("/snap/bin/blender"),
            Path("/var/lib/flatpak/exports/bin/org.blender.Blender"),
            home / ".local/share/flatpak/exports/bin/org.blender.Blender",
        ]
    return found


def find_blender(
    environ: Mapping[str, str] | None = None, platform: str | None = None
) -> Path | None:
    """The first existing Blender executable, or ``None``.

    Raises:
        IngestError: if ``MESH2BRICK_BLENDER`` names a file that does not exist
            (a typo should not silently fall back to another Blender).
    """
    environ = os.environ if environ is None else environ
    explicit = environ.get(BLENDER_ENV)
    if explicit and not Path(explicit).expanduser().is_file():
        msg = f"{BLENDER_ENV}={explicit} does not exist"
        raise IngestError(msg)
    for path in candidate_paths(environ, platform):
        if path.is_file():
            return path
    return None


def blender_command(
    blender: Path, source: Path, script: Path, glb: Path, report: Path
) -> list[str]:
    """Command line that exports ``source`` with the export script."""
    return [
        str(blender),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "-noaudio",
        str(source),
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        str(glb),
        str(report),
    ]


class BlenderLoader:
    """Loader for ``.blend`` (needs a Blender installation, extra ``blender``)."""

    suffixes: frozenset[str] = frozenset({".blend"})

    def __init__(
        self, blender: Path | None = None, *, timeout_s: float = TIMEOUT_S
    ) -> None:
        self._blender = blender
        self._timeout_s = timeout_s

    def load(
        self,
        path: Path,
        config: InputConfig | None = None,  # noqa: ARG002 - no options yet
    ) -> RawModel:
        """Export the visible objects with Blender and read them (millimetres).

        Raises:
            IngestError: if Blender is missing, fails, times out or the scene
                has no visible geometry.
        """
        blender = self._blender or find_blender()
        if blender is None:
            raise IngestError(INSTALL_HINT)
        source = path.resolve()
        with (
            tempfile.TemporaryDirectory(prefix="mesh2brick-blend-") as tmp,
            resources.as_file(
                resources.files("mesh2brick.ingest") / "blender_export.py"
            ) as script,
        ):
            glb, report_path = Path(tmp) / "scene.glb", Path(tmp) / "scene.json"
            command = blender_command(blender, source, script, glb, report_path)
            self._run(command, path)
            report = _read_report(report_path, path)
            exported: list[str] = list(report.get("exported", []))
            hidden: list[str] = list(report.get("hidden", []))
            if not exported or not glb.is_file():
                msg = f"{path.name} has no visible mesh, curve or text objects" + (
                    f" (hidden: {', '.join(hidden[:5])})" if hidden else ""
                )
                raise IngestError(msg)
            scale = unit_scale(report)
            return read_gltf(
                glb,
                mm_per_unit=MM_PER_METRE * scale,
                notes=blend_notes(report),
            )

    def _run(self, command: Sequence[str], path: Path) -> None:
        try:
            # A fixed argument list, no shell: file names cannot inject commands.
            done = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self._timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            msg = (
                f"Blender did not finish exporting {path.name} within "
                f"{self._timeout_s:.0f} s"
            )
            raise IngestError(msg) from error
        except OSError as error:
            msg = f"cannot start Blender ({command[0]}): {error.strerror or error}"
            raise IngestError(msg) from error
        if done.returncode != 0:
            output = (done.stderr or "") + (done.stdout or "")
            tail = "\n".join(output.strip().splitlines()[-_OUTPUT_TAIL:])
            msg = (
                f"Blender could not export {path.name} (exit code "
                f"{done.returncode}):\n{tail}"
            )
            raise IngestError(msg)


def _read_report(report_path: Path, path: Path) -> dict[str, Any]:
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        msg = f"Blender did not report what it exported from {path.name}: {error}"
        raise IngestError(msg) from error
    if not isinstance(data, dict):
        msg = f"unexpected export report for {path.name}"
        raise IngestError(msg)
    return data


def unit_scale(report: Mapping[str, Any]) -> float:
    """Metres per Blender unit, without single-precision noise.

    Blender stores the scale as a 32-bit float: 0.001 arrives as
    0.0010000000474974513.
    """
    scale = float(report.get("unit_scale") or 1.0)
    return float(f"{scale:.6g}") if scale > 0 else 1.0


def blend_notes(report: Mapping[str, Any]) -> tuple[str, ...]:
    """Remarks for the user about what Blender exported."""
    exported = list(report.get("exported", []))
    hidden = list(report.get("hidden", []))
    scale = unit_scale(report)
    unit = str(report.get("length_unit", "")).lower()
    notes = [
        (
            f"read with Blender {report.get('blender', '?')}: {len(exported)} "
            "visible object(s), modifiers applied"
        )
    ]
    if hidden:
        shown = ", ".join(hidden[:5]) + (", ..." if len(hidden) > 5 else "")  # noqa: PLR2004
        notes.append(f"skipped {len(hidden)} hidden object(s): {shown}")
    if scale != 1.0:
        notes.append(
            f"Blender unit = {MM_PER_METRE * scale:g} mm (scene unit scale {scale:g}"
            + (f", {unit}" if unit else "")
            + ")"
        )
    return tuple(notes)
