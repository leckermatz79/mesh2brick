# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Regenerate the mesh fixtures in tests/fixtures/ (deterministic).

    uv run python scripts/make_fixtures.py

The generated meshes are dedicated to the public domain (CC0-1.0), see
tests/fixtures/README.md. STEP files are written by a small AP214 writer
below (boxes as B-rep solids, optional colours), so no CAD kernel is needed
to make them.
"""

from __future__ import annotations

import math
from itertools import count
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from trimesh.exchange.obj import export_obj

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def cube_10mm() -> trimesh.Trimesh:
    """A 10 mm cube resting on z = 0 (acceptance: 1 x 1 stud, 1 brick)."""
    cube = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    cube.apply_translation((5.0, 5.0, 5.0))
    return cube


def sphere_r10() -> trimesh.Trimesh:
    """Sphere of radius 10 mm (acceptance: < 15 % volume error at 32 studs)."""
    return trimesh.creation.icosphere(subdivisions=4, radius=10.0)


def l_bracket() -> trimesh.Trimesh:
    """An inverted L: 10 x 10 x 40 mm post with a 20 mm arm overhanging at the top."""
    profile = np.array(
        [[0, 0], [10, 0], [10, 30], [30, 30], [30, 40], [0, 40]], dtype=np.float64
    )
    triangles = np.array([[0, 1, 2], [0, 2, 5], [2, 3, 4], [2, 4, 5]])
    mesh = trimesh.creation.extrude_triangulation(profile, triangles, height=10.0)
    # The profile was drawn in x/y; stand it up so y becomes z.
    mesh.apply_transform(
        trimesh.transformations.rotation_matrix(math.pi / 2, (1, 0, 0))
    )
    mesh.apply_translation(-mesh.bounds[0])
    return mesh


def torus() -> trimesh.Trimesh:
    """Ring (major radius 20 mm, tube radius 6 mm): an enclosed hole."""
    return trimesh.creation.torus(
        major_radius=20.0, minor_radius=6.0, major_sections=48, minor_sections=24
    )


def bunny_lowpoly() -> trimesh.Trimesh:
    """A low-poly bunny from overlapping ellipsoids (organic shape, thin ears).

    Overlapping closed shells are intentional: voxelization must union them.
    """

    def blob(
        centre: tuple[float, float, float],
        radii: tuple[float, float, float],
        tilt_deg: float = 0.0,
    ) -> trimesh.Trimesh:
        shape = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
        shape.apply_scale(radii)
        if tilt_deg:
            shape.apply_transform(
                trimesh.transformations.rotation_matrix(
                    math.radians(tilt_deg), (0, 1, 0)
                )
            )
        shape.apply_translation(centre)
        return shape

    parts = [
        blob((0.0, 0.0, 14.0), (18.0, 13.0, 13.0)),  # body
        blob((16.0, 0.0, 28.0), (9.0, 8.0, 8.5)),  # head
        blob((12.0, 4.0, 41.0), (2.5, 3.2, 10.0), tilt_deg=-18.0),  # ears
        blob((12.0, -4.0, 41.0), (2.5, 3.2, 10.0), tilt_deg=-18.0),
        blob((-18.0, 0.0, 16.0), (4.5, 4.5, 4.5)),  # tail
        blob((11.0, 7.0, 3.0), (7.0, 3.5, 3.0)),  # front feet
        blob((11.0, -7.0, 3.0), (7.0, 3.5, 3.0)),
        blob((-8.0, 9.0, 5.0), (9.0, 4.0, 5.0)),  # hind legs
        blob((-8.0, -9.0, 5.0), (9.0, 4.0, 5.0)),
    ]
    bunny = trimesh.util.concatenate(parts)
    bunny.apply_translation((0.0, 0.0, -bunny.bounds[0][2]))
    return bunny


# ------------------------------------------------------------------ coloured
def _coloured(
    mesh: trimesh.Trimesh, name: str, rgb: tuple[int, int, int]
) -> trimesh.Trimesh:
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.SimpleMaterial(name=name, diffuse=[*rgb, 255])
    )
    return mesh


def toadstool() -> dict[str, bytes]:
    """Red cap with white spots on a pale stem (OBJ + MTL material colours).

    The spots are small spheres half sunk into the cap: their hidden halves
    and the cap surface under them must not decide the colour.
    """
    stem = trimesh.creation.cylinder(radius=6.0, height=16.0, sections=32)
    stem.apply_translation((0.0, 0.0, 8.0))
    cap = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    cap.apply_scale((16.0, 16.0, 9.0))
    cap.apply_translation((0.0, 0.0, 18.0))
    parts = [
        _coloured(stem, "stem", (236, 226, 198)),
        _coloured(cap, "cap", (200, 25, 25)),
    ]
    for index, (azimuth, elevation) in enumerate(
        [(0, 70), (60, 40), (150, 45), (220, 35), (290, 50), (110, 15), (330, 20)]
    ):
        az, el = math.radians(azimuth), math.radians(elevation)
        direction = np.array(
            [math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)]
        )
        point = direction * np.array([16.0, 16.0, 9.0]) + (0.0, 0.0, 18.0)
        spot = trimesh.creation.icosphere(subdivisions=2, radius=3.2)
        spot.apply_translation(point)
        parts.append(_coloured(spot, f"spot{index}", (250, 250, 250)))
    text, files = export_obj(
        trimesh.Scene(parts), mtl_name="toadstool.mtl", return_texture=True
    )
    return {"toadstool.obj": text.encode(), **files}


def vertex_colors() -> dict[str, bytes]:
    """Sphere with vertex colours: yellow top half, blue bottom half (PLY)."""
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=10.0)
    top = sphere.vertices[:, 2] > 0
    colours = np.where(top[:, None], [250, 205, 30, 255], [20, 60, 170, 255])
    sphere.visual = trimesh.visual.ColorVisuals(
        sphere, vertex_colors=colours.astype(np.uint8)
    )
    return {"vertex_colors.ply": sphere.export(file_type="ply")}


def textured_cube() -> dict[str, bytes]:
    """20 mm cube with a 2 x 2 texture: top face green, all others orange (OBJ)."""
    texture = np.zeros((64, 64, 3), dtype=np.uint8)
    texture[:32, :32] = (40, 160, 60)  # top-left quadrant: green (v > 0.5)
    texture[:32, 32:] = (240, 130, 20)
    texture[32:, :] = (240, 130, 20)
    corners = np.array(
        [
            # (normal axis, sign) -> 4 corners counter-clockwise from outside
            [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]],  # top (+z)
            [[0, 0, 0], [0, 1, 0], [1, 1, 0], [1, 0, 0]],  # bottom
            [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]],  # -y
            [[1, 1, 0], [0, 1, 0], [0, 1, 1], [1, 1, 1]],  # +y
            [[0, 1, 0], [0, 0, 0], [0, 0, 1], [0, 1, 1]],  # -x
            [[1, 0, 0], [1, 1, 0], [1, 1, 1], [1, 0, 1]],  # +x
        ],
        dtype=np.float64,
    )
    vertices = corners.reshape(-1, 3) * 20.0
    faces = np.array(
        [[q * 4, q * 4 + 1, q * 4 + 2] for q in range(6)]
        + [[q * 4, q * 4 + 2, q * 4 + 3] for q in range(6)]
    )
    quad_uv = {
        "green": [[0.1, 0.6], [0.4, 0.6], [0.4, 0.9], [0.1, 0.9]],
        "orange": [[0.6, 0.1], [0.9, 0.1], [0.9, 0.4], [0.6, 0.4]],
    }
    uv = np.array([quad_uv["green"]] + [quad_uv["orange"]] * 5).reshape(-1, 2)
    cube = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    material = trimesh.visual.material.SimpleMaterial(
        name="textured_cube", image=Image.fromarray(texture)
    )
    cube.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    text, files = export_obj(cube, mtl_name="textured_cube.mtl", return_texture=True)
    return {"textured_cube.obj": text.encode(), **files}


# ------------------------------------------------------------------ STEP
Box = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float] | None,
]
# Corner i has x = high if bit 0, y = high if bit 1, z = high if bit 2. Loops run
# counter-clockwise seen from outside, so the plane normals point outwards.
_QUADS = (
    ((0, 2, 3, 1), (0, 0, -1)),
    ((4, 5, 7, 6), (0, 0, 1)),
    ((0, 1, 5, 4), (0, -1, 0)),
    ((2, 6, 7, 3), (0, 1, 0)),
    ((0, 4, 6, 2), (-1, 0, 0)),
    ((1, 3, 7, 5), (1, 0, 0)),
)


class StepWriter:
    """Minimal AP214 writer: one product, one B-rep solid per box (mm)."""

    def __init__(self) -> None:
        self._ids = count(1)
        self._lines: list[str] = []

    def add(self, entity: str) -> int:
        """Append ``#n=entity;`` and return ``n``."""
        number = next(self._ids)
        self._lines.append(f"#{number}={entity};")
        return number

    @staticmethod
    def num(value: float) -> str:
        """STEP real literal."""
        return repr(float(value)).upper()

    def point(self, p: tuple[float, ...]) -> int:
        """A CARTESIAN_POINT."""
        return self.add(f"CARTESIAN_POINT('',({','.join(self.num(c) for c in p)}))")

    def direction(self, d: tuple[float, ...]) -> int:
        """A DIRECTION."""
        return self.add(f"DIRECTION('',({','.join(self.num(c) for c in d)}))")

    def context(self) -> int:
        """Millimetre geometric context."""
        length = self.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
        angle = self.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
        solid = self.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
        uncertainty = self.add(
            f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#{length},"
            "'distance_accuracy_value','confusion accuracy')"
        )
        return self.add(
            "(GEOMETRIC_REPRESENTATION_CONTEXT(3)"
            f"GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{uncertainty}))"
            f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{length},#{angle},#{solid}))"
            "REPRESENTATION_CONTEXT('Context #1','3D Context with units'))"
        )

    def box(self, low: tuple[float, ...], high: tuple[float, ...]) -> int:
        """A MANIFOLD_SOLID_BREP for the box ``low``..``high``."""
        coords = [
            tuple(high[k] if i >> k & 1 else low[k] for k in range(3)) for i in range(8)
        ]
        vertices = [self.add(f"VERTEX_POINT('',#{self.point(c)})") for c in coords]
        edges: dict[tuple[int, int], int] = {}
        faces = []
        for loop, normal in _QUADS:
            oriented = []
            for k in range(4):
                a, b = loop[k], loop[(k + 1) % 4]
                key = (min(a, b), max(a, b))
                if key not in edges:
                    edges[key] = self._edge(coords, vertices, key)
                sense = ".T." if (a, b) == key else ".F."
                oriented.append(
                    self.add(f"ORIENTED_EDGE('',*,*,#{edges[key]},{sense})")
                )
            loop_id = self.add(f"EDGE_LOOP('',({','.join(f'#{e}' for e in oriented)}))")
            bound = self.add(f"FACE_OUTER_BOUND('',#{loop_id},.T.)")
            reference = (1, 0, 0) if normal[0] == 0 else (0, 1, 0)
            placement = self.add(
                f"AXIS2_PLACEMENT_3D('',#{self.point(coords[loop[0]])},"
                f"#{self.direction(normal)},#{self.direction(reference)})"
            )
            plane = self.add(f"PLANE('',#{placement})")
            faces.append(self.add(f"ADVANCED_FACE('',(#{bound}),#{plane},.T.)"))
        shell = self.add(f"CLOSED_SHELL('',({','.join(f'#{x}' for x in faces)}))")
        return self.add(f"MANIFOLD_SOLID_BREP('',#{shell})")

    def _edge(
        self, coords: list[tuple[float, ...]], vertices: list[int], key: tuple[int, int]
    ) -> int:
        start, end = coords[key[0]], coords[key[1]]
        delta = tuple(end[k] - start[k] for k in range(3))
        size = sum(abs(c) for c in delta)
        unit = self.direction(tuple(c / size for c in delta))
        vector = self.add(f"VECTOR('',#{unit},{self.num(size)})")
        line = self.add(f"LINE('',#{self.point(start)},#{vector})")
        return self.add(
            f"EDGE_CURVE('',#{vertices[key[0]]},#{vertices[key[1]]},#{line},.T.)"
        )

    def colour(self, solid: int, rgb: tuple[float, float, float]) -> int:
        """A STYLED_ITEM giving ``solid`` the surface colour ``rgb`` (0..1)."""
        colour = self.add(f"COLOUR_RGB('',{','.join(self.num(c) for c in rgb)})")
        fill_colour = self.add(f"FILL_AREA_STYLE_COLOUR('',#{colour})")
        fill = self.add(f"FILL_AREA_STYLE('',(#{fill_colour}))")
        area = self.add(f"SURFACE_STYLE_FILL_AREA(#{fill})")
        side = self.add(f"SURFACE_SIDE_STYLE('',(#{area}))")
        usage = self.add(f"SURFACE_STYLE_USAGE(.BOTH.,#{side})")
        assignment = self.add(f"PRESENTATION_STYLE_ASSIGNMENT((#{usage}))")
        return self.add(f"STYLED_ITEM('color',(#{assignment}),#{solid})")

    def document(self, name: str, boxes: list[Box]) -> str:
        """The whole file: product structure, solids, colours."""
        app = self.add("APPLICATION_CONTEXT('automotive design')")
        self.add(
            "APPLICATION_PROTOCOL_DEFINITION('international standard',"
            f"'automotive_design',2000,#{app})"
        )
        product_context = self.add(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
        product = self.add(f"PRODUCT('{name}','{name}','',(#{product_context}))")
        formation = self.add(f"PRODUCT_DEFINITION_FORMATION('','',#{product})")
        definition_context = self.add(
            f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')"
        )
        definition = self.add(
            f"PRODUCT_DEFINITION('design','',#{formation},#{definition_context})"
        )
        shape = self.add(f"PRODUCT_DEFINITION_SHAPE('','',#{definition})")
        context = self.context()
        solids, styled = [], []
        for low, high, rgb in boxes:
            solids.append(self.box(low, high))
            if rgb is not None:
                styled.append(self.colour(solids[-1], rgb))
        origin = self.add(
            f"AXIS2_PLACEMENT_3D('',#{self.point((0, 0, 0))},"
            f"#{self.direction((0, 0, 1))},#{self.direction((1, 0, 0))})"
        )
        items = ",".join(f"#{s}" for s in [*solids, origin])
        representation = self.add(
            f"ADVANCED_BREP_SHAPE_REPRESENTATION('{name}',({items}),#{context})"
        )
        self.add(f"SHAPE_DEFINITION_REPRESENTATION(#{shape},#{representation})")
        if styled:
            self.add(
                "MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',"
                f"({','.join(f'#{s}' for s in styled)}),#{context})"
            )
        header = [
            "ISO-10303-21;",
            "HEADER;",
            "FILE_DESCRIPTION(('mesh2brick test fixture (CC0-1.0)'),'2;1');",
            (
                f"FILE_NAME('{name}.step','2026-11-01T00:00:00',(''),(''),"
                "'mesh2brick','mesh2brick','');"
            ),
            "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));",
            "ENDSEC;",
            "DATA;",
        ]
        return "\n".join([*header, *self._lines, "ENDSEC;", "END-ISO-10303-21;", ""])


def step_boxes(boxes: list[Box], *, name: str) -> str:
    """Axis-aligned boxes ``(low, high, rgb 0..1 or None)`` as one STEP product."""
    return StepWriter().document(name, boxes)


def cube_10mm_step() -> dict[str, bytes]:
    """The STEP twin of cube_10mm.stl (acceptance: identical grids)."""
    text = step_boxes([((0, 0, 0), (10, 10, 10), None)], name="cube_10mm")
    return {"cube_10mm.step": text.encode()}


def two_bodies_step() -> dict[str, bytes]:
    """Two touching 10 mm cubes, red and blue: multi-body and STEP colours."""
    text = step_boxes(
        [
            ((0, 0, 0), (10, 10, 10), (0.8, 0.1, 0.1)),
            ((10, 0, 0), (20, 10, 10), (0.1, 0.2, 0.8)),
        ],
        name="two_bodies",
    )
    return {"two_bodies.step": text.encode()}


BUILDERS = {
    "cube_10mm.stl": cube_10mm,
    "sphere_r10.stl": sphere_r10,
    "l_bracket.stl": l_bracket,
    "torus.stl": torus,
    "bunny_lowpoly.stl": bunny_lowpoly,
}
FILE_BUILDERS = (
    toadstool,
    vertex_colors,
    textured_cube,
    cube_10mm_step,
    two_bodies_step,
)


def main() -> None:
    """Write every fixture and print a one-line summary each."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, build in BUILDERS.items():
        mesh = build()
        mesh.export(FIXTURES / name)
        print(
            f"{name}: {len(mesh.faces)} faces, extents {np.round(mesh.extents, 2)}, "
            f"watertight={mesh.is_watertight}, volume={mesh.volume:.0f} mm3"
        )
    for build_files in FILE_BUILDERS:
        for name, raw in build_files().items():
            # Text files end with exactly one newline (pre-commit rule).
            data = raw.rstrip(b"\n") + b"\n" if name.endswith((".obj", ".mtl")) else raw
            (FIXTURES / name).write_bytes(data)
            print(f"{name}: {len(data):,} bytes")


if __name__ == "__main__":
    main()
