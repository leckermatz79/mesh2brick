# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""glTF import: Y up, metres and linear colours per the glTF 2.0 spec (Phase 8)."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

import numpy as np
import pytest
import trimesh

from mesh2brick.config import load_settings
from mesh2brick.ingest import IngestError, load_model
from mesh2brick.ingest.colors import linear_to_srgb, srgb_to_linear, to_bytes
from mesh2brick.ingest.gltf import GltfLoader, gltf_colors, linear_vertex_colors
from mesh2brick.voxel.voxelize import voxelize

if TYPE_CHECKING:
    from pathlib import Path


def _glb(path: Path, meshes: dict[str, trimesh.Trimesh]) -> Path:
    scene = trimesh.Scene()
    for name, mesh in meshes.items():
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    path.write_bytes(scene.export(file_type="glb"))
    return path


def _pbr_box(extents: tuple[float, float, float], linear: tuple[float, ...]):
    box = trimesh.creation.box(extents=extents)
    material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=[*(round(c * 255) for c in linear), 255]
    )
    box.visual = trimesh.visual.TextureVisuals(material=material)
    return box


def test_y_up_metres_become_z_up_millimetres(tmp_path: Path) -> None:
    # 10 mm x 40 mm (tall, along glTF's +Y) x 20 mm (along glTF's +Z = front).
    path = _glb(
        tmp_path / "tall.glb", {"Tower": trimesh.creation.box((0.01, 0.04, 0.02))}
    )
    raw = GltfLoader().load(path)
    assert raw.names == ("Tower",)
    np.testing.assert_allclose(raw.parts[0].extents, [10, 20, 40], atol=1e-6)


def test_node_transforms_and_names_are_kept(tmp_path: Path) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box((0.01,) * 3), node_name="Left")
    scene.add_geometry(
        trimesh.creation.box((0.01,) * 3),
        node_name="Right",
        transform=trimesh.transformations.translation_matrix((0.05, 0, 0)),
    )
    path = tmp_path / "two.glb"
    path.write_bytes(scene.export(file_type="glb"))
    raw = GltfLoader().load(path)
    centres = {
        name: part.centroid for name, part in zip(raw.names, raw.parts, strict=True)
    }
    assert set(centres) == {"Left", "Right"}
    np.testing.assert_allclose(
        centres["Right"] - centres["Left"], [50, 0, 0], atol=1e-6
    )


def test_material_colour_is_linear_and_converted_to_srgb(tmp_path: Path) -> None:
    linear = (0.578, 0.011, 0.003)  # LEGO Red (201, 26, 9) in linear light
    path = _glb(tmp_path / "red.glb", {"Red": _pbr_box((0.01,) * 3, linear)})
    raw = GltfLoader().load(path)
    colors = raw.colors[0]
    assert colors is not None
    assert colors.kinds == ("cad",)
    r, g, b = (int(v) for v in colors.cad[0])
    assert abs(r - 201) <= 2
    assert g < 40
    assert b < 25


def test_vertex_colours_with_material_multiply_the_factor() -> None:
    """trimesh keeps COLOR_0 as a raw vertex attribute next to the material."""
    box = _pbr_box((1, 1, 1), (1.0, 0.5, 1.0))
    half = np.full((len(box.vertices), 4), 65535, dtype=np.uint16)
    half[:, 1] = 65535 // 2  # linear 0.5 green ...
    box.visual.vertex_attributes["color"] = half
    colors = gltf_colors(box)
    assert colors is not None
    assert set(colors.kinds) == {"cad", "vertex"}
    assert colors.vertex is not None
    # ... times the factor's 0.5 green = linear 0.25 -> sRGB 137.
    expected = int(to_bytes(linear_to_srgb(np.array([0.25])))[0])
    assert abs(int(colors.vertex[0, 0, 1]) - expected) <= 1
    assert int(colors.vertex[0, 0, 0]) == 255


def test_vertex_colours_without_material(tmp_path: Path) -> None:
    box = trimesh.creation.box((0.01,) * 3)
    box.visual = trimesh.visual.ColorVisuals(
        box, vertex_colors=np.tile([255, 128, 0, 255], (len(box.vertices), 1))
    )
    path = _glb(tmp_path / "vc.glb", {"Painted": box})
    colors = GltfLoader().load(path).colors[0]
    assert colors is not None
    assert colors.kinds == ("vertex",)
    assert colors.vertex is not None
    # 128 is read as linear light, as glTF requires: sRGB 188.
    srgb_mid = int(to_bytes(linear_to_srgb(np.array([128 / 255])))[0])
    assert tuple(int(v) for v in colors.vertex[0, 0]) == (255, srgb_mid, 0)


def test_linear_vertex_colors_formats() -> None:
    box = trimesh.creation.box()
    count = len(box.vertices)
    box.visual = trimesh.visual.TextureVisuals()
    box.visual.vertex_attributes["color"] = np.array([[2.0, 0.5, -1.0, 1.0]] * count)
    np.testing.assert_allclose(linear_vertex_colors(box), [[1.0, 0.5, 0.0]] * count)
    box.visual.vertex_attributes["color"] = np.ones((count - 1, 4))  # wrong length
    assert linear_vertex_colors(box) is None
    assert linear_vertex_colors(trimesh.creation.box()) is None


def _triangle_gltf(path: Path, colour: list[int]) -> Path:
    """One triangle with a normalised uint16 COLOR_0, as Blender writes it."""
    positions = np.array([[0, 0, 0], [0.01, 0, 0], [0, 0.01, 0]], dtype="<f4")
    colours = np.array([colour] * 3, dtype="<u2")
    blob = positions.tobytes() + colours.tobytes()
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Painted", "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}}]}],
        "buffers": [
            {
                "byteLength": len(blob),
                "uri": "data:application/octet-stream;base64,"
                + base64.b64encode(blob).decode(),
            }
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 24},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0, 0, 0],
                "max": [0.01, 0.01, 0],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "normalized": True,
                "count": 3,
                "type": "VEC4",
            },
        ],
    }
    path.write_text(json.dumps(gltf))
    return path


def test_wide_vertex_colours_are_not_wrapped(tmp_path: Path) -> None:
    """trimesh 5.2 wraps uint16 colours modulo 256 (14146 -> 66); we do not."""
    # Linear 14146 / 65535 = 0.2159 is sRGB 0.5.
    path = _triangle_gltf(tmp_path / "painted.gltf", [65535, 14146, 0, 65535])
    colors = GltfLoader().load(path).colors[0]
    assert colors is not None
    assert colors.vertex is not None
    assert tuple(int(v) for v in colors.vertex[0, 0]) == (255, 128, 0)


def test_uncoloured_gltf_has_no_colours(tmp_path: Path) -> None:
    path = _glb(tmp_path / "plain.glb", {"Plain": trimesh.creation.box((0.01,) * 3)})
    assert GltfLoader().load(path).colors == ()


def test_gltf_and_stl_cube_give_identical_grids(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    cube = trimesh.load(fixtures_dir / "cube_10mm.stl")
    cube.apply_scale(0.001)
    # STL is z up; glTF is y up: rotate the cube's +Z onto glTF's +Y.
    cube.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, (1, 0, 0)))
    path = _glb(tmp_path / "cube.glb", {"Cube": cube})
    settings = load_settings(None, ["input.target_studs=12"])
    grids = [
        voxelize(load_model(p, settings.input), settings).grid
        for p in (fixtures_dir / "cube_10mm.stl", path)
    ]
    assert grids[0].shape == grids[1].shape
    assert np.array_equal(grids[0].occupancy, grids[1].occupancy)


def test_broken_and_empty_files(tmp_path: Path) -> None:
    broken = tmp_path / "broken.glb"
    broken.write_bytes(b"glTF not really")
    with pytest.raises(IngestError, match=r"cannot read broken\.glb"):
        GltfLoader().load(broken)
    empty = tmp_path / "empty.gltf"
    empty.write_text('{"asset": {"version": "2.0"}, "scenes": [{"nodes": []}]}')
    with pytest.raises(IngestError, match="no triangle meshes"):
        GltfLoader().load(empty)


def test_srgb_round_trip_helpers_are_inverse() -> None:
    values = np.linspace(0, 1, 11)
    np.testing.assert_allclose(
        linear_to_srgb(srgb_to_linear(values)), values, atol=1e-9
    )
