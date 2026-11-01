# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Colour sources of meshes (ingest) and colour transfer onto the grid (voxel)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from mesh2brick.config import ColorConfig, InputConfig, load_settings
from mesh2brick.ingest import load_model
from mesh2brick.ingest.base import FaceColors, RawModel
from mesh2brick.ingest.colors import (
    concat,
    corner_permutation,
    extend,
    from_visual,
    linear_to_srgb,
    parse_hex_color,
    permute_corners,
    srgb_to_linear,
    take,
)
from mesh2brick.ingest.normalize import normalize, parts_are_closed
from mesh2brick.voxel.color import (
    model_colors,
    paint,
    sample_rgb,
    surface_samples,
    usable_kinds,
)
from mesh2brick.voxel.voxelize import Lattice, voxelize

RED, BLUE, GREEN = (200, 20, 20), (20, 40, 200), (30, 160, 50)


def identity(rgb: np.ndarray) -> np.ndarray:
    """Test quantizer: encodes the red channel as the 'colour code'."""
    return np.asarray(rgb, dtype=np.int32)[:, 0]


def box(
    low: tuple[float, float, float], high: tuple[float, float, float]
) -> trimesh.Trimesh:
    lo, hi = np.asarray(low, float), np.asarray(high, float)
    mesh = trimesh.creation.box(extents=hi - lo)
    mesh.apply_translation((lo + hi) / 2)
    return mesh


def material(mesh: trimesh.Trimesh, rgb: tuple[int, int, int]) -> trimesh.Trimesh:
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.SimpleMaterial(name="m", diffuse=[*rgb, 255])
    )
    return mesh


def model_of(*parts: trimesh.Trimesh, **raw: object) -> object:
    return normalize(
        RawModel(parts=parts, names=tuple(f"p{i}" for i in range(len(parts))), **raw),  # type: ignore[arg-type]
        InputConfig(),
        source=Path("test.obj"),
    )


def grid_colors(model: object, *overrides: str) -> tuple[np.ndarray, tuple[str, ...]]:
    settings = load_settings(
        None, ["input.scale_mode=mm", "input.mm_per_stud=8", *overrides]
    )
    result = voxelize(model, settings, quantize=identity)  # type: ignore[arg-type]
    grid = result.grid
    return grid.color[grid.occupancy], result.warnings


# ------------------------------------------------------------------ colour maths
def test_srgb_round_trip_and_reference_values() -> None:
    values = np.linspace(0, 1, 11)
    np.testing.assert_allclose(
        linear_to_srgb(srgb_to_linear(values)), values, atol=1e-12
    )
    assert srgb_to_linear(np.array([0.8]))[0] == pytest.approx(0.6038, abs=1e-4)


@pytest.mark.parametrize(
    ("text", "rgb"),
    [("#FF8000", (255, 128, 0)), ("#ff800080", (255, 128, 0)), ("00ff00", (0, 255, 0))],
)
def test_parse_hex_color(text: str, rgb: tuple[int, int, int]) -> None:
    assert parse_hex_color(text) == rgb


@pytest.mark.parametrize("text", ["", "#FFF", "#GG0000", "red"])
def test_parse_hex_color_rejects(text: str) -> None:
    assert parse_hex_color(text) is None


# ------------------------------------------------------------------ extraction
def test_material_colour_is_cad() -> None:
    colors = from_visual(material(box((0, 0, 0), (1, 1, 1)), RED))
    assert colors is not None
    assert colors.kinds == ("cad",)
    assert (colors.cad == RED).all()


def test_pbr_factor_is_converted_from_linear_light() -> None:
    mesh = box((0, 0, 0), (1, 1, 1))
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[0.6038, 0.0, 0.0, 1.0]
        )
    )
    colors = from_visual(mesh)
    assert colors is not None
    assert tuple(colors.cad[0]) == pytest.approx((204, 0, 0), abs=1)


def test_vertex_and_face_colours() -> None:
    mesh = box((0, 0, 0), (1, 1, 1))
    mesh.visual.vertex_colors = np.tile([*GREEN, 255], (len(mesh.vertices), 1))
    colors = from_visual(mesh)
    assert colors is not None
    assert colors.kinds == ("vertex",)
    assert colors.vertex is not None
    assert (colors.vertex == GREEN).all()
    faced = box((0, 0, 0), (1, 1, 1))
    faced.visual.face_colors = np.tile([*BLUE, 255], (len(faced.faces), 1))
    face_colors = from_visual(faced)
    assert face_colors is not None
    assert face_colors.vertex is not None
    assert (face_colors.vertex == BLUE).all()


def test_texture_with_pbr_tint_and_size_limit() -> None:
    mesh = box((0, 0, 0), (1, 1, 1))
    image = Image.new("RGB", (4000, 2), (255, 255, 255))
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2)),
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=image, baseColorFactor=[1.0, 0.2140, 0.0, 1.0]
        ),
    )
    colors = from_visual(mesh)
    assert colors is not None
    assert colors.kinds == ("texture",)
    texture = colors.textures[0]
    assert max(texture.shape[:2]) <= 2048
    assert tuple(texture[0, 0]) == pytest.approx((255, 128, 0), abs=2)


def test_meshes_without_colour() -> None:
    assert from_visual(box((0, 0, 0), (1, 1, 1))) is None
    untitled = box((0, 0, 0), (1, 1, 1))
    untitled.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.SimpleMaterial(diffuse=[102, 102, 102, 255])
    )
    assert from_visual(untitled) is None


# ------------------------------------------------------------------ bookkeeping
def test_face_colors_validation() -> None:
    with pytest.raises(ValueError, match="one entry per face"):
        FaceColors(cad=np.zeros((2, 3), np.uint8), cad_mask=np.zeros(3, bool))
    with pytest.raises(ValueError, match="need a mask"):
        FaceColors(
            cad=np.zeros((1, 3), np.uint8),
            cad_mask=np.zeros(1, bool),
            vertex=np.zeros((1, 3, 3), np.uint8),
        )
    with pytest.raises(ValueError, match="texture indices"):
        FaceColors(
            cad=np.zeros((1, 3), np.uint8),
            cad_mask=np.zeros(1, bool),
            uv=np.zeros((1, 3, 2), np.float32),
        )


def test_raw_model_colour_validation() -> None:
    mesh = box((0, 0, 0), (1, 1, 1))
    with pytest.raises(ValueError, match="every part or none"):
        RawModel(parts=(mesh, mesh), names=("a", "b"), colors=(None,))
    with pytest.raises(ValueError, match="one entry per face"):
        RawModel(parts=(mesh,), names=("a",), colors=(FaceColors.uniform(RED, 3),))


def test_concat_take_extend() -> None:
    textured = FaceColors(
        cad=np.zeros((2, 3), np.uint8),
        cad_mask=np.zeros(2, bool),
        uv=np.zeros((2, 3, 2), np.float32),
        texture=np.zeros(2, np.int32),
        textures=(np.zeros((1, 1, 3), np.uint8),),
    )
    vertex = FaceColors(
        cad=np.zeros((1, 3), np.uint8),
        cad_mask=np.zeros(1, bool),
        vertex=np.full((1, 3, 3), 9, np.uint8),
        vertex_mask=np.ones(1, bool),
    )
    merged = concat(
        [textured, None, vertex, textured, FaceColors.uniform(RED, 1)], [2, 3, 1, 2, 1]
    )
    assert merged is not None
    assert merged.face_count == 9
    assert merged.texture is not None
    assert merged.texture.tolist() == [0, 0, -1, -1, -1, -1, 1, 1, -1]
    assert len(merged.textures) == 2
    assert merged.mask("vertex").tolist() == [False] * 5 + [True] + [False] * 3
    assert merged.mask("cad").tolist() == [False] * 8 + [True]
    kept = take(merged, np.arange(9) >= 5)
    assert kept.face_count == 4
    longer = extend(kept, 2)
    assert longer.face_count == 6
    assert not longer.mask("cad")[-2:].any()
    assert concat([None, None], [1, 1]) is None


def test_corner_permutation_tracks_flipped_faces() -> None:
    before = np.array([[0, 1, 2], [3, 4, 5]])
    after = np.array([[0, 1, 2], [5, 4, 3]])
    perm = corner_permutation(before, after)
    assert perm is not None
    assert perm.tolist() == [[0, 1, 2], [2, 1, 0]]
    assert corner_permutation(before, before) is None
    with pytest.raises(ValueError, match="face count"):
        corner_permutation(before, before[:1])
    colors = FaceColors(
        cad=np.zeros((2, 3), np.uint8),
        cad_mask=np.zeros(2, bool),
        vertex=np.arange(18, dtype=np.uint8).reshape(2, 3, 3),
        vertex_mask=np.ones(2, bool),
    )
    flipped = permute_corners(colors, perm)
    assert flipped.vertex is not None
    assert flipped.vertex[1].tolist() == [[15, 16, 17], [12, 13, 14], [9, 10, 11]]


def test_normalize_keeps_vertex_colours_on_their_corners() -> None:
    """An inside-out mesh gets flipped; each corner keeps its own colour."""
    mesh = trimesh.creation.icosphere(subdivisions=1, radius=5.0)
    mesh.invert()
    height = mesh.vertices[:, 2]
    mesh.visual.vertex_colors = np.c_[
        np.where(height > 0, 250, 10),
        np.zeros((len(height), 2)),
        np.full(len(height), 255),
    ].astype(np.uint8)
    model = model_of(mesh)
    assert model.colors is not None  # type: ignore[attr-defined]
    corners = np.asarray(model.mesh.vertices)[np.asarray(model.mesh.faces)]  # type: ignore[attr-defined]
    vertex = model.colors.vertex  # type: ignore[attr-defined]
    assert ((corners[:, :, 2] > 0) == (vertex[:, :, 0] > 128)).all()


def test_touching_closed_parts_count_as_watertight() -> None:
    a, b = box((0, 0, 0), (8, 8, 8)), box((8, 0, 0), (16, 8, 8))
    model = model_of(a, b)
    assert not model.mesh.is_watertight  # type: ignore[attr-defined]
    assert model.watertight  # type: ignore[attr-defined]
    faces = np.asarray(model.mesh.faces)  # type: ignore[attr-defined]
    assert not parts_are_closed(faces, np.full(len(faces), -1, np.int32))
    assert not parts_are_closed(faces[:0], np.zeros(0, np.int32))


def test_multi_body_error_mode(tmp_path: Path) -> None:
    raw = RawModel(parts=(box((0, 0, 0), (1, 1, 1)),) * 2, names=("a", "b"))
    with pytest.raises(ValueError, match="2 bodies"):
        normalize(raw, InputConfig(multi_body="error"), source=tmp_path / "x.step")


# ------------------------------------------------------------------ transfer
def test_two_coloured_halves() -> None:
    model = model_of(
        material(box((0, 0, 0), (16, 8, 8)), RED),
        material(box((16, 0, 0), (32, 8, 8)), BLUE),
    )
    settings = load_settings(None, ["input.scale_mode=mm"])
    grid = voxelize(model, settings, quantize=identity).grid  # type: ignore[arg-type]
    assert grid.color[:2, :, :].ravel().tolist() == [RED[0]] * grid.color[:2].size
    assert set(grid.color[2:, :, :].ravel().tolist()) == {BLUE[0]}


def test_hidden_surfaces_do_not_vote() -> None:
    """A blue box fully inside a red one must not tint the red shell."""
    outer = material(box((0, 0, 0), (24, 24, 24)), RED)
    inner = material(box((6, 6, 6), (18, 18, 18)), BLUE)
    colors, _ = grid_colors(model_of(outer, inner), "voxel.height_unit=plate")
    assert set(colors.tolist()) == {RED[0]}


def test_embedded_detail_wins_its_visible_cells() -> None:
    """A blue knob sunk 4 mm into a red block: its hidden part never votes."""
    block = material(box((0, 0, 0), (32, 32, 16)), RED)
    knob = material(box((8, 8, 12), (24, 24, 22.4)), BLUE)
    settings = load_settings(None, ["input.scale_mode=mm", "voxel.height_unit=plate"])
    model = model_of(block, knob)
    grid = voxelize(model, settings, quantize=identity).grid  # type: ignore[arg-type]
    assert grid.shape == (4, 4, 7)
    assert set(grid.color[1:3, 1:3, 5:].ravel().tolist()) == {BLUE[0]}
    top_of_block = grid.color[:, :, 4]
    assert top_of_block[0].tolist() == [RED[0]] * 4
    assert set(top_of_block[1:3, 1:3].ravel().tolist()) <= {RED[0], BLUE[0]}
    assert grid.color[1, 1, 0] == RED[0]


def test_thin_detail_colours_the_cells_below() -> None:
    """A 0.8 mm blue coating on a red block fills no cell but shows on top."""
    block = material(box((0, 0, 0), (32, 32, 16)), RED)
    tile = material(box((0, 0, 16), (32, 32, 16.8)), BLUE)
    settings = load_settings(None, ["input.scale_mode=mm", "voxel.height_unit=plate"])
    grid = voxelize(model_of(block, tile), settings, quantize=identity).grid  # type: ignore[arg-type]
    assert grid.shape == (4, 4, 5)
    top = grid.color[:, :, -1]
    corners = top[[0, 0, 3, 3], [0, 3, 0, 3]]
    assert (top == BLUE[0]).sum() == 16 - (corners != BLUE[0]).sum()
    assert (top[1:3, :] == BLUE[0]).all()
    assert set(grid.color[:, :, 0].ravel().tolist()) == {RED[0]}


def test_vertex_colours_are_interpolated() -> None:
    mesh = box((0, 0, 0), (32, 8, 8))
    x = mesh.vertices[:, 0]
    mesh.visual.vertex_colors = np.c_[
        np.where(x > 0 + 16, 240, 0), np.zeros((len(x), 2)), np.full(len(x), 255)
    ].astype(np.uint8)
    colors, _ = grid_colors(model_of(mesh), "color.mode=vertex")
    assert colors.min() < 60  # a gradient from dark ...
    assert colors.max() > 180  # ... to bright


def test_texture_lookup_uses_v_up() -> None:
    mesh = box((0, 0, 0), (16, 16, 16))
    image = np.zeros((2, 1, 3), np.uint8)
    image[0] = (200, 0, 0)  # top row = v near 1
    image[1] = (100, 0, 0)
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.tile([0.5, 0.9], (len(mesh.vertices), 1)),
        material=trimesh.visual.material.SimpleMaterial(image=Image.fromarray(image)),
    )
    colors, _ = grid_colors(model_of(mesh), "color.mode=texture")
    assert set(colors.tolist()) == {200}


@pytest.mark.parametrize(
    ("mode", "expected", "note"),
    [
        ("auto", {200}, None),
        ("texture", {200}, None),
        ("vertex", {90}, "texture colours, ignored"),
        ("cad", {4}, "has no cad colours"),
        ("single", {4}, None),
    ],
)
def test_modes_pick_the_allowed_source(
    mode: str, expected: set[int], note: str | None
) -> None:
    textured = box((0, 0, 0), (16, 16, 16))
    textured.visual = trimesh.visual.TextureVisuals(
        uv=np.full((len(textured.vertices), 2), 0.5),
        material=trimesh.visual.material.SimpleMaterial(
            image=Image.new("RGB", (1, 1), (200, 0, 0))
        ),
    )
    coloured = box((0, 0, 0), (16, 16, 16))
    coloured.visual.vertex_colors = np.tile(
        [90, 0, 0, 255], (len(coloured.vertices), 1)
    )
    raw = RawModel(parts=(textured,), names=("t",))
    model = normalize(raw, InputConfig(), source=Path("t.obj"))
    vertex_model = normalize(
        RawModel(parts=(coloured,), names=("v",)), InputConfig(), source=Path("v.ply")
    )
    merged = concat([model.colors, vertex_model.colors], [len(model.mesh.faces), 0])
    assert merged is not None
    both = FaceColors(
        cad=merged.cad,
        cad_mask=merged.cad_mask,
        vertex=np.full((merged.face_count, 3, 3), 90, np.uint8),
        vertex_mask=np.ones(merged.face_count, bool),
        uv=merged.uv,
        texture=merged.texture,
        textures=merged.textures,
    )
    rich = type(model)(
        mesh=model.mesh, source=model.source, part_names=model.part_names,
        watertight=True, face_part=model.face_part, colors=both,
    )  # fmt: skip
    colors, warnings = grid_colors(rich, f"color.mode={mode}")
    assert set(colors.tolist()) == expected
    if note:
        assert any(note in w for w in warnings)


def test_uncoloured_parts_get_the_single_colour() -> None:
    model = model_of(
        material(box((0, 0, 0), (16, 8, 8)), BLUE), box((16, 0, 0), (32, 8, 8))
    )
    colors, warnings = grid_colors(model, "color.single_color=7")
    assert set(colors.tolist()) == {BLUE[0], 7}
    assert any("has no colour" in w for w in warnings)


def test_model_colours_need_a_quantizer() -> None:
    model = model_of(material(box((0, 0, 0), (8, 8, 8)), RED))
    with pytest.raises(ValueError, match="need a palette"):
        voxelize(model, load_settings(None, ["input.scale_mode=mm"]))  # type: ignore[arg-type]


def test_usable_kinds() -> None:
    model = model_of(material(box((0, 0, 0), (8, 8, 8)), RED))
    assert usable_kinds(model, "auto") == ("cad",)  # type: ignore[arg-type]
    assert usable_kinds(model, "height_bands") == ()  # type: ignore[arg-type]
    assert usable_kinds(model_of(box((0, 0, 0), (8, 8, 8))), "auto") == ()  # type: ignore[arg-type]


def test_grid_modes_ignore_model_colours() -> None:
    model = model_of(material(box((0, 0, 0), (8, 8, 24)), RED))
    lattice = Lattice(origin=(0, 0, 0), pitch=8.0, cell_height=9.6, shape=(1, 1, 3))
    grid, notes = model_colors(
        np.ones((1, 1, 3), bool),
        lattice,
        model,
        ColorConfig(mode="height_bands", bands=(1, 2, 3)),
        None,  # type: ignore[arg-type]
    )
    assert grid.ravel().tolist() == [1, 2, 3]
    assert notes == ()


# ------------------------------------------------------------------ low-level
def test_surface_samples_land_on_the_solid_side() -> None:
    """Faces exactly on cell boundaries are assigned to the filled cell."""
    mesh = box((0, 0, 0), (16, 16, 9.6))
    lattice = Lattice(origin=(0, 0, 0), pitch=8.0, cell_height=9.6, shape=(2, 2, 1))
    samples = surface_samples(np.asarray(mesh.triangles), lattice)
    assert len(samples.face)
    assert ((samples.cell >= 0) & (samples.cell < (2, 2, 1))).all()
    # z rays: 8 x 8, x and y rays: 8 x 5 (4.8 rays per brick height -> 5);
    # every ray crosses two faces.
    assert len(samples.face) == 2 * (8 * 8 + 8 * 5 + 5 * 8)


def test_open_meshes_keep_all_crossings() -> None:
    mesh = box((0, 0, 0), (16, 16, 16))
    lattice = Lattice(origin=(0, 0, 0), pitch=8.0, cell_height=8.0, shape=(2, 2, 2))
    closed = surface_samples(np.asarray(mesh.triangles), lattice)
    open_ = surface_samples(np.asarray(mesh.triangles), lattice, boundary_only=False)
    assert len(open_.face) == len(closed.face)
    empty = surface_samples(np.zeros((0, 3, 3)), lattice)
    assert len(empty.face) == 0


def test_paint_votes_and_fills() -> None:
    occupancy = np.ones((3, 1, 1), bool)
    cells = np.array([[0, 0, 0], [0, 0, 0], [0, 0, 0], [2, 0, 0], [2, 0, 0]])
    codes = np.array([5, 5, 7, 9, 3], dtype=np.int32)
    grid = paint(occupancy, cells, codes, (8.0, 8.0, 9.6), fallback=4)
    assert grid[0, 0, 0] == 5  # majority
    assert grid[2, 0, 0] == 9  # tie -> higher code
    assert grid[1, 0, 0] in {5, 9}
    empty = paint(
        occupancy, np.zeros((0, 3), np.int64), np.zeros(0, np.int32), (1, 1, 1), 4
    )
    assert set(empty.ravel().tolist()) == {4}


def test_sample_rgb_prefers_detail_and_reports_unknown() -> None:
    colors = FaceColors(
        cad=np.array([RED, RED], np.uint8),
        cad_mask=np.array([True, False]),
        vertex=np.full((2, 3, 3), 50, np.uint8),
        vertex_mask=np.array([True, False]),
    )
    face = np.array([0, 1])
    bary = np.full((2, 3), 1 / 3)
    rgb, known = sample_rgb(colors, face, bary, ("cad", "vertex"))
    assert rgb[0].tolist() == [50, 50, 50]
    assert known.tolist() == [True, False]
    rgb, _ = sample_rgb(colors, face, bary, ("cad",))
    assert rgb[0].tolist() == list(RED)


# ------------------------------------------------------------------ fixtures
@pytest.mark.parametrize(
    ("name", "kind", "studs"),
    [
        ("toadstool.obj", "cad", 16),
        ("vertex_colors.ply", "vertex", 12),
        ("textured_cube.obj", "texture", 8),
    ],
)
def test_coloured_fixtures(
    fixtures_dir: Path, name: str, kind: str, studs: int
) -> None:
    settings = load_settings(None, [f"input.target_studs={studs}"])
    model = load_model(fixtures_dir / name, settings.input)
    assert model.colors is not None
    assert model.colors.kinds == (kind,)
    assert model.watertight
    grid = voxelize(model, settings, quantize=identity).grid
    assert len(np.unique(grid.color[grid.occupancy])) >= 2


def test_textured_cube_top_is_green(fixtures_dir: Path) -> None:
    settings = load_settings(None, ["input.target_studs=8", "voxel.height_unit=plate"])
    model = load_model(fixtures_dir / "textured_cube.obj", settings.input)
    grid = voxelize(
        model, settings, quantize=lambda rgb: np.asarray(rgb)[:, 1].astype(np.int32)
    ).grid
    top = grid.color[1:-1, 1:-1, -1]
    assert set(top.ravel().tolist()) == {160}  # green channel of the top quadrant
    assert set(grid.color[:, :, 0][grid.occupancy[:, :, 0]].ravel().tolist()) == {130}
