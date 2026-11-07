# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Build tests/fixtures/rocket.blend inside Blender (deterministic geometry).

    blender --background --factory-startup --python scripts/make_blend_fixture.py \
        -- tests/fixtures/rocket.blend

Runs in Blender's own Python (3.10 in Blender 4.0), so it uses only ``bpy``,
``mathutils`` and the standard library. The model is dedicated to the public
domain (CC0-1.0), see tests/fixtures/README.md. It exercises what the
``.blend`` import has to handle:

* millimetre scene units (1 Blender unit = 1 mm, unit scale 0.001),
* material colours (Principled BSDF base colour) on several objects,
* modifiers that must be applied: one fin plus an Array modifier turning
  copies around a helper empty = four fins,
* a hidden helper object and a camera/light that must not be imported.
"""

from __future__ import annotations

import math
import sys

import bpy

# sRGB colours of the parts (LEGO White, Red, Bright Blue, Dark Bluish Gray).
COLOURS = {
    "White": (244, 244, 244),
    "Red": (201, 26, 9),
    "Blue": (0, 85, 191),
    "Grey": (99, 95, 98),
}


def srgb_to_linear(channel: int) -> float:
    """Blender stores material colours in linear light."""
    value = channel / 255.0
    if value <= 0.04045:  # noqa: PLR2004 - IEC 61966-2-1
        return value / 12.92
    return float(((value + 0.055) / 1.055) ** 2.4)


def material(name: str) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    r, g, b = (srgb_to_linear(c) for c in COLOURS[name])
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    mat.diffuse_color = (r, g, b, 1.0)
    return mat


def assign(obj: bpy.types.Object, mat: bpy.types.Material) -> bpy.types.Object:
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def fin_mesh() -> bpy.types.Mesh:
    """A trapezoid fin, 4 mm thick, pointing along +x."""
    profile = [(8.0, 0.0), (26.0, 0.0), (26.0, 9.0), (8.0, 36.0)]  # (radius, z)
    half = 2.0
    verts = [(r, y, z) for y in (-half, half) for r, z in profile]
    faces = [
        (0, 1, 2, 3),  # front (y = -half)
        (7, 6, 5, 4),  # back
        (0, 4, 5, 1),  # bottom
        (1, 5, 6, 2),  # outer edge
        (2, 6, 7, 3),  # slanted top
        (3, 7, 4, 0),  # inner edge (inside the body)
    ]
    mesh = bpy.data.meshes.new("Fin")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def build(path: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = "MILLIMETERS"
    mats = {name: material(name) for name in COLOURS}

    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48, radius=12.0, depth=60.0, location=(0.0, 0.0, 42.0)
    )
    assign(bpy.context.object, mats["White"]).name = "Body"
    bpy.ops.mesh.primitive_cone_add(
        vertices=48, radius1=12.0, radius2=0.0, depth=28.0, location=(0, 0, 86.0)
    )
    assign(bpy.context.object, mats["Red"]).name = "Nose"
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32,
        radius=5.5,
        depth=6.0,
        location=(0.0, -10.5, 56.0),
        rotation=(math.pi / 2, 0.0, 0.0),
    )
    assign(bpy.context.object, mats["Blue"]).name = "Window"
    bpy.ops.mesh.primitive_cone_add(
        vertices=32, radius1=9.0, radius2=7.0, depth=9.0, location=(0, 0, 8.5)
    )
    assign(bpy.context.object, mats["Grey"]).name = "Nozzle"

    pivot = bpy.data.objects.new("Fin pivot", None)  # an empty: no geometry
    pivot.rotation_euler = (0.0, 0.0, math.pi / 2)
    scene.collection.objects.link(pivot)
    fins = bpy.data.objects.new("Fins", fin_mesh())
    scene.collection.objects.link(fins)
    assign(fins, mats["Red"])
    array = fins.modifiers.new("Four fins", "ARRAY")
    array.count = 4
    array.use_relative_offset = False
    array.use_object_offset = True
    array.offset_object = pivot

    bpy.ops.mesh.primitive_cube_add(size=200.0, location=(0.0, 0.0, -100.0))
    helper = bpy.context.object
    helper.name = "Helper (hidden)"
    helper.hide_set(state=True)

    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(camera)
    light = bpy.data.objects.new("Light", bpy.data.lights.new("Light", "SUN"))
    scene.collection.objects.link(light)

    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)


if __name__ == "__main__":
    build(sys.argv[sys.argv.index("--") + 1])
