# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Regenerate the mesh fixtures in tests/fixtures/ (deterministic).

    uv run python scripts/make_fixtures.py

The generated meshes are dedicated to the public domain (CC0-1.0), see
tests/fixtures/README.md.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import trimesh

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


BUILDERS = {
    "cube_10mm.stl": cube_10mm,
    "sphere_r10.stl": sphere_r10,
    "l_bracket.stl": l_bracket,
    "torus.stl": torus,
    "bunny_lowpoly.stl": bunny_lowpoly,
}


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


if __name__ == "__main__":
    main()
