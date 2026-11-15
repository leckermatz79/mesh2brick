# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Shape fidelity: surface deviation of a brick model to its input mesh."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import trimesh
from tests.helpers import make_brick

from mesh2brick.fidelity import (
    STUD_RADIUS_MM,
    grid_mesh,
    lego_frame,
    point_mesh_distances,
    surface_deviation,
    surface_samples,
    triangle_distances,
    visible_parts,
    weighted_percentile,
)
from mesh2brick.model import STUD_HEIGHT_MM, BrickModel, BuildStep, PlacedPart
from mesh2brick.voxel.grid import VoxelGrid


def _model(*parts: PlacedPart) -> BrickModel:
    return BrickModel(name="m", parts=parts, steps=(BuildStep(),))


def _box(low: tuple[float, ...], high: tuple[float, ...]) -> trimesh.Trimesh:
    return trimesh.creation.box(bounds=np.array([low, high], dtype=float))


def _deviation(model: BrickModel, mesh: trimesh.Trimesh) -> tuple[float, float]:
    found = surface_deviation(
        model, np.asarray(mesh.vertices), np.asarray(mesh.faces, dtype=np.int64)
    )
    return found.mean_mm, found.p95_mm


def test_a_brick_on_its_own_box_deviates_only_by_its_studs() -> None:
    brick = make_brick("3001", 0, 0, 0, 0)  # 2 x 4 studs, 3 plates
    exact = _box((0, 0, 0), (16, 32, 9.6))
    mean, p95 = _deviation(_model(brick), exact)
    # The stud tops sit 1.7 mm above the box; the sides of the studs 0.85 mm.
    disc, side = np.pi * STUD_RADIUS_MM**2, 2 * np.pi * STUD_RADIUS_MM * STUD_HEIGHT_MM
    area = 2 * (16 * 32 + 16 * 9.6 + 32 * 9.6) + 8 * side
    expected = 8 * (disc * STUD_HEIGHT_MM + side * STUD_HEIGHT_MM / 2) / area
    assert mean == pytest.approx(expected, rel=0.02)
    # The stud tops are more than 5 % of the surface.
    assert p95 == pytest.approx(STUD_HEIGHT_MM, abs=1e-6)


def test_without_studs_a_part_on_its_own_box_has_no_deviation() -> None:
    tile_like = replace(make_brick("3001", 0, 0, 0, 0), studs=())
    mean, p95 = _deviation(_model(tile_like), _box((0, 0, 0), (16, 32, 9.6)))
    assert mean == pytest.approx(0.0, abs=1e-9)
    assert p95 == pytest.approx(0.0, abs=1e-9)


def test_a_part_one_plate_too_high_shows_the_plate() -> None:
    plain = replace(make_brick("3001", 0, 0, 0, 0), studs=())
    lower = _box((0, 0, 0), (16, 32, 6.4))  # two plates
    _mean, p95 = _deviation(_model(plain), lower)
    assert p95 == pytest.approx(3.2, abs=1e-6)


def test_tiles_have_no_studs_and_hidden_faces_do_not_count() -> None:
    low = make_brick("3001", 0, 0, 0, 0)
    tile = PlacedPart(
        part="87079", color=4, x=0, y=0, layer=3, yaw=0, step=0, category="tile",
        cells=tuple((i, j, 3) for i in range(2) for j in range(4)),
    )  # fmt: skip
    points, weights = surface_samples(_model(low, tile))
    # Outside only: 2 x 4 top, bottom and sides of a 4-plate block, no studs.
    assert weights.sum() == pytest.approx(2 * (16 * 32) + 2 * (16 + 32) * 12.8)
    assert points[:, 2].max() == pytest.approx(12.8, abs=1e-6)  # flat, no studs


def test_cavities_of_hollow_models_are_not_surface() -> None:
    cells = tuple(
        (x, y, z)
        for x in range(3)
        for y in range(3)
        for z in range(3)
        if (x, y, z) != (1, 1, 1)
    )
    shell = PlacedPart(
        part="x", color=4, x=0, y=0, layer=0, yaw=0, cells=cells, step=0, studs=()
    )
    _points, weights = surface_samples(_model(shell))
    assert weights.sum() == pytest.approx(2 * 24 * 24 + 4 * 24 * 9.6)


def test_slopes_are_sampled_on_their_sloped_face() -> None:
    cells = tuple((0, y, z) for y in (0, 1) for z in range(3))
    slope = PlacedPart(
        part="3040b", color=4, x=0, y=0, layer=0, yaw=0, cells=cells, step=0,
        category="slope", studs=((0, 1),),
    )  # fmt: skip
    points, _ = surface_samples(_model(slope))
    over_slope = points[points[:, 1] < 8]
    # The sloped column falls from 9.6 mm to the 1.6 mm lip; nothing at full height.
    assert over_slope[:, 2].max() < 9.6
    assert over_slope[:, 2].min() == pytest.approx(0.0)


def _hollow_box_with_inner_slope() -> tuple[PlacedPart, PlacedPart]:
    """A 4 x 4 box, 4 bricks high, with a cavity; a slope on the cavity floor."""
    cavity = {(x, y, z) for x in (1, 2) for y in (1, 2) for z in range(3, 9)}
    cells = tuple(
        (x, y, z)
        for x in range(4)
        for y in range(4)
        for z in range(12)
        if (x, y, z) not in cavity
    )
    shell = PlacedPart(
        part="x", color=4, x=0, y=0, layer=0, yaw=0, cells=cells, step=0, studs=()
    )
    slope = PlacedPart(
        part="3040b", color=4, x=1, y=1, layer=3, yaw=0, step=0, category="slope",
        cells=tuple((1, y, z) for y in (1, 2) for z in range(3, 6)), studs=((1, 2),),
    )  # fmt: skip
    return shell, slope


def test_slopes_on_the_inner_wall_of_a_hollow_model_are_not_surface() -> None:
    # Up to 2.0 every sloped top counted, also those facing a cavity (2.1 fix).
    shell, slope = _hollow_box_with_inner_slope()
    _points, alone = surface_samples(_model(shell))
    _points, with_slope = surface_samples(_model(shell, slope))
    outside = 2 * 32 * 32 + 4 * 32 * 38.4
    assert alone.sum() == pytest.approx(outside)
    assert with_slope.sum() == pytest.approx(outside)


def test_visible_parts_touch_the_air_around_the_model() -> None:
    shell, slope = _hollow_box_with_inner_slope()
    assert visible_parts(_model(shell, slope)) == {0}
    outer = replace(
        slope, x=0, cells=tuple((5, y, z) for y in (0, 1) for z in range(3))
    )
    assert visible_parts(_model(shell, slope, outer)) == {0, 2}
    assert visible_parts(_model()) == frozenset()


def _slope_2x1() -> PlacedPart:
    """A 3040b falling towards -y: stud column (0, 1), sloped column (0, 0)."""
    return PlacedPart(
        part="3040b", color=4, x=0, y=0, layer=0, yaw=0, step=0, category="slope",
        cells=tuple((0, y, z) for y in (0, 1) for z in range(3)), studs=((0, 1),),
    )  # fmt: skip


def test_sides_showing_above_a_slope_are_surface() -> None:
    # A 1 x 1 brick beside the sloped column shows its side above the slope:
    # the face falls from 3 plates to the 0.5 plate lip, so 1.25 plates on
    # average are open (1.25 x 3.2 mm x 8 mm = 32 mm²); the slope's own side
    # there (1.75 plates on average, 44.8 mm²) is hidden.
    slope = _slope_2x1()
    beside = PlacedPart(
        part="3005", color=4, x=1, y=0, layer=0, yaw=0, step=0,
        cells=tuple((1, 0, z) for z in range(3)), studs=(),
    )  # fmt: skip
    _p, alone = surface_samples(_model(slope))
    points, both = surface_samples(_model(slope, beside))
    brick_faces = 2 * 64 + 3 * 8 * 9.6  # top, bottom, three free sides
    assert both.sum() == pytest.approx(alone.sum() - 44.8 + brick_faces + 32.0)
    side = points[np.isclose(points[:, 0], 8.0) & (points[:, 2] > 0)]
    assert len(side)  # samples on the brick's side at x = 8 mm, above the slope


def test_triangle_distances_match_brute_force_sampling() -> None:
    rng = np.random.default_rng(1)
    triangles = rng.normal(size=(200, 3, 3))
    points = rng.normal(size=(200, 3)) * 2
    exact = triangle_distances(points, triangles)
    s, t = np.meshgrid(np.linspace(0, 1, 201), np.linspace(0, 1, 201))
    keep = (s + t) <= 1
    s, t = s[keep], t[keep]
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    dense = (
        a[:, None] + (b - a)[:, None] * s[None, :, None] + (c - a)[:, None] * t[None, :, None]
    )  # fmt: skip
    sampled = np.linalg.norm(dense - points[:, None], axis=2).min(axis=1)
    assert np.all(exact <= sampled + 1e-9)
    assert np.allclose(exact, sampled, atol=0.02)


def test_degenerate_triangles_measure_to_their_points() -> None:
    line = np.array([[[0.0, 0, 0], [1, 0, 0], [2, 0, 0]]])
    assert triangle_distances(np.array([[1.0, 1, 0]]), line)[0] == pytest.approx(1.0)


def test_point_mesh_distances_are_exact_for_points_far_from_big_triangles() -> None:
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=40.0)
    rng = np.random.default_rng(2)
    points = rng.uniform(-60, 60, size=(300, 3))
    found = point_mesh_distances(
        points, np.asarray(mesh.vertices), np.asarray(mesh.faces, dtype=np.int64)
    )
    triangles = np.asarray(mesh.triangles)
    brute = np.array(
        [
            triangle_distances(np.repeat(p[None], len(triangles), 0), triangles).min()
            for p in points
        ]
    )
    assert np.allclose(found, brute)


def test_lego_frame_scales_model_millimetres_to_studs_of_8_mm() -> None:
    vertices = np.array([[10.0, 10.0, 0.0], [14.0, 12.0, 4.8]])
    frame = lego_frame(vertices, origin_mm=(10.0, 10.0, 0.0), pitch_mm=4.0)
    assert np.allclose(frame, [[0, 0, 0], [8, 4, 9.6]])


def test_grid_mesh_is_the_outer_surface_of_the_cells() -> None:
    occupancy = np.zeros((2, 1, 1), dtype=bool)
    occupancy[:, 0, 0] = True
    grid = VoxelGrid(
        occupancy=occupancy,
        color=np.where(occupancy, 4, -1).astype(np.int32),
        pitch_mm=8.0,
    )
    vertices, faces = grid_mesh(grid)
    mesh = trimesh.Trimesh(vertices, faces, process=True)
    assert mesh.area == pytest.approx(2 * 16 * 8 + 2 * 16 * 9.6 + 2 * 8 * 9.6)
    assert np.allclose(mesh.bounds, [[0, 0, 0], [16, 8, 9.6]])


def test_weighted_percentile_weights_by_area() -> None:
    values = np.array([0.0, 1.0, 2.0])
    assert weighted_percentile(values, np.array([1.0, 1.0, 98.0]), 50) == 2.0
    assert weighted_percentile(values, np.array([96.0, 1.0, 3.0]), 95) == 0.0
