# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Export script that runs *inside* Blender for the ``.blend`` loader.

mesh2brick never imports ``bpy`` itself. :mod:`mesh2brick.ingest.blender`
starts Blender in background mode and passes this file with ``--python``::

    blender --background --factory-startup --disable-autoexec model.blend \
        --python-exit-code 1 --python blender_export.py -- scene.glb scene.json

It writes the visible geometry of the active scene to a binary glTF
(modifiers applied, materials, textures and colour attributes kept, Y up as
the glTF spec requires) and a small JSON report: Blender version, scene unit
scale, which objects were exported and which were skipped as hidden. The
``.blend`` file itself is never written.

The script must run on Blender's bundled Python (3.10 in Blender 4.0) and
uses only ``bpy`` and the standard library. Everything except :func:`main`
is plain Python, so it is unit-tested without Blender.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

GEOMETRY_TYPES = frozenset({"MESH", "CURVE", "SURFACE", "FONT", "META"})
"""Object types whose evaluated geometry becomes triangles."""
CONVERT_TYPES = GEOMETRY_TYPES - {"MESH"}
"""Types the glTF exporter may skip, converted to meshes first (in memory)."""

WANTED_OPTIONS: dict[str, Any] = {
    "export_format": "GLB",
    "use_visible": True,
    "use_active_scene": True,
    "export_apply": True,
    "export_yup": True,
    "export_texcoords": True,
    "export_normals": False,
    "export_materials": "EXPORT",
    "export_image_format": "AUTO",
    "export_colors": True,  # Blender <= 4.1
    "export_vertex_color": "ACTIVE",  # Blender >= 4.2
    "export_attributes": False,
    "export_cameras": False,
    "export_lights": False,
    "export_extras": False,
    "export_animations": False,
    "export_skins": False,
    "export_morph": False,
    "export_draco_mesh_compression_enable": False,
    "export_gpu_instances": False,
    "check_existing": False,
}
"""glTF exporter options; names Blender's version does not know are dropped."""


def export_options(available: set[str], filepath: str) -> dict[str, Any]:
    """The exporter keyword arguments this Blender version understands."""
    options = {key: value for key, value in WANTED_OPTIONS.items() if key in available}
    options["filepath"] = filepath
    return options


def script_arguments(argv: list[str]) -> tuple[Path, Path]:
    """The ``.glb`` and ``.json`` output paths after Blender's ``--`` separator.

    Raises:
        SystemExit: if the two paths are missing.
    """
    try:
        rest = argv[argv.index("--") + 1 :]
    except ValueError:
        rest = []
    if len(rest) != 2:  # noqa: PLR2004 - glb and json
        msg = "usage: blender ... --python blender_export.py -- OUT.glb OUT.json"
        raise SystemExit(msg)
    return Path(rest[0]), Path(rest[1])


def report(
    *,
    version: str,
    scene: str,
    unit_scale: float,
    length_unit: str,
    exported: list[str],
    hidden: list[str],
) -> dict[str, Any]:
    """The JSON report the loader reads back."""
    return {
        "blender": version,
        "scene": scene,
        "unit_scale": unit_scale,
        "length_unit": length_unit,
        "exported": sorted(exported),
        "hidden": sorted(hidden),
    }


def main() -> None:  # pragma: no cover - runs inside Blender only
    """Export the active scene's visible geometry (Blender entry point)."""
    import bpy  # noqa: PLC0415 - only available inside Blender

    glb, info = script_arguments(sys.argv)
    scene = bpy.context.scene
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    objects = list(scene.objects)
    visible = [o for o in objects if o.visible_get()]
    geometry = [o for o in visible if o.type in GEOMETRY_TYPES]
    instances = [
        o
        for o in visible
        if o.type == "EMPTY"
        and o.instance_type == "COLLECTION"
        and o.instance_collection is not None
    ]
    hidden = [
        o.name for o in objects if o.type in GEOMETRY_TYPES and not o.visible_get()
    ]
    to_convert = [o for o in geometry if o.type in CONVERT_TYPES]
    if to_convert:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in to_convert:
            obj.select_set(state=True)
        bpy.context.view_layer.objects.active = to_convert[0]
        bpy.ops.object.convert(target="MESH")
    exported = [o.name for o in geometry] + [o.name for o in instances]
    if exported:
        available = {
            p.identifier for p in bpy.ops.export_scene.gltf.get_rna_type().properties
        }
        bpy.ops.export_scene.gltf(**export_options(available, str(glb)))
    data = report(
        version=bpy.app.version_string,
        scene=scene.name,
        unit_scale=float(scene.unit_settings.scale_length),
        length_unit=str(scene.unit_settings.length_unit),
        exported=exported,
        hidden=hidden,
    )
    info.write_text(json.dumps(data, indent=1), encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
