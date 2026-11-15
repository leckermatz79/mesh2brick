# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Slopes on tilted stairs: rating, choice, the backend pass (ROADMAP 8)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import trimesh
from tests.helpers import make_brick

from mesh2brick.backends.legolization import (
    LegolizationBackend,
    restricted_catalog,
    to_brick_model,
)
from mesh2brick.backends.slopes import SlopeReport, apply_slopes, with_slopes
from mesh2brick.catalog.whitelist import Whitelist
from mesh2brick.config import Settings, load_settings
from mesh2brick.fidelity import surface_deviation
from mesh2brick.ingest.base import MeshModel
from mesh2brick.model import BrickModel, BuildStep, PlacedPart
from mesh2brick.place.slopes import SLOPE_PARTS, SlopeSite, slope_sites
from mesh2brick.voxel import slopes as rating
from mesh2brick.voxel.flat import flat_tops
from mesh2brick.voxel.grid import VoxelGrid
from mesh2brick.voxel.io import load_npz, save_npz
from mesh2brick.voxel.voxelize import fill_fractions, hollow, plan_lattice, voxelize

PITCH = 8.0
"""One stud = 8 model mm, so LEGO mm = model mm."""
RED = 4
_PARTS = (
    "3005", "3004", "3622", "3010", "3009", "3003", "3002", "3001", "3024", "3023",
    "3623", "3710", "3666", "3460", "3022", "3021", "3020", "3070b", "3069b",
    "3040b", "3039", "4286",
)  # fmt: skip
PLUS_X, MINUS_X, PLUS_Y, MINUS_Y = range(4)
FORTY_FIVE, THIRTY_THREE = range(2)


# ------------------------------------------------------------------ meshes
def _profile(points: list[tuple[float, float]], depth: float) -> trimesh.Trimesh:
    """A prism: ``points`` (x, z, counter-clockwise) extruded ``depth`` along y."""
    profile = np.asarray(points, dtype=float)
    fan = np.array([[0, i, i + 1] for i in range(1, len(points) - 1)])
    prism = trimesh.creation.extrude_triangulation(profile, fan, height=depth)
    prism.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    prism.apply_translation(-prism.bounds[0])
    return prism


def _ramp(degrees: float, length: float = 64.0, depth: float = 32.0) -> trimesh.Trimesh:
    """A wedge whose top falls towards +x at ``degrees`` (a 4 mm lip at the end)."""
    rise = length * np.tan(np.radians(degrees))
    return _profile([(0, 0), (length, 0), (length, 4), (0, 4 + rise)], depth)


def _rate(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray, Any]:
    """(occupancy, slope gains, lattice) of ``mesh`` on brick cells."""
    lattice = plan_lattice(np.asarray(mesh.bounds), pitch=PITCH, height_unit="brick")
    triangles = np.asarray(mesh.triangles)
    occupancy = fill_fractions(triangles, lattice) >= 0.5
    flat = flat_tops(triangles, occupancy, lattice, lego_cell_height_mm=9.6)
    gains = rating.slope_gains(
        triangles, occupancy, lattice, flat, lego_cell_height_mm=9.6
    )
    return occupancy, gains, lattice


def _directions(gains: np.ndarray) -> set[int]:
    return {int(d) for d in np.argwhere(np.isfinite(gains))[:, 3]}


def _kinds(gains: np.ndarray) -> Counter[int]:
    return Counter(int(k) for k in np.argwhere(np.isfinite(gains))[:, 4])


# ------------------------------------------------------------------ rating
def test_a_45_degree_ramp_gets_slopes_falling_its_way() -> None:
    occupancy, gains, _ = _rate(_ramp(45.0))
    assert occupancy.any()
    assert _directions(gains) == {PLUS_X}
    assert _kinds(gains)[FORTY_FIVE] > 0
    assert np.nanmin(gains) > 0


def test_no_slope_where_the_stair_already_lies_closer() -> None:
    # One brick per stud (50°), the surface through the middle of every tread
    # and riser: a slope would lie a quarter cell off, the stair is closer.
    _, gains, _ = _rate(_ramp(50.0, length=48.0))
    assert not np.isfinite(gains).any()


def test_a_30_degree_ramp_gets_33_degree_slopes() -> None:
    ramp = _ramp(30.0)
    ramp.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, (0, 0, 1)))
    ramp.apply_translation(-ramp.bounds[0])  # now it falls towards -y
    _, gains, _ = _rate(ramp)
    assert _directions(gains) == {MINUS_Y}
    assert _kinds(gains)[THIRTY_THREE] > 0


def test_a_dome_gets_slopes_all_round_but_not_on_its_apex() -> None:
    dome = trimesh.creation.icosphere(subdivisions=4, radius=80.0)
    occupancy, gains, _ = _rate(dome)
    assert _directions(gains) == {PLUS_X, MINUS_X, PLUS_Y, MINUS_Y}
    top = int(np.argwhere(occupancy)[:, 2].max())
    apex = np.argwhere(occupancy[:, :, top]).mean(axis=0)
    for x, y, z, d, k in np.argwhere(np.isfinite(gains)):
        dx, dy = rating.DIRECTIONS[d]
        for step in range(1, rating.RUNS[k] + 1):
            column = np.asarray([x + dx * step, y + dy * step])
            assert z < top or np.abs(column + 0.5 - (apex + 0.5)).max() > 1.0


def test_boxes_get_no_slopes_not_even_on_a_top_above_the_mesh() -> None:
    # 25 mm high: the voxels end 0.4 bricks above the top, a slope would lie
    # closer than the step, but the face is level (that is a job for tiles).
    box = trimesh.creation.box(bounds=[[0, 0, 0], [48, 32, 25]])
    _, gains, _ = _rate(box)
    assert not np.isfinite(gains).any()


def test_inside_lengths_along_a_ray_are_exact() -> None:
    crossings = rating._Crossings(
        ray=np.asarray([3, 3, 5, 5], dtype=np.int64),
        height=np.asarray([1.0, 2.5, 0.2, 0.7]),
        sign=np.asarray([1, -1, 1, -1], dtype=np.int8),
        normal=np.zeros((4, 3)),
    )
    profiles = rating.ray_profiles(crossings, nz=4)
    rays = np.asarray([3, 3, 3, 3, 5, 4], dtype=np.int64)
    heights = np.asarray([0.5, 2.0, 3.0, 1.75, 1.0, 2.0])
    found = profiles.inside_below(rays, heights)
    assert np.allclose(found, [0.0, 1.0, 1.5, 0.75, 0.5, 0.0])


def _wedge_model(occupancy: np.ndarray, sites: list[SlopeSite]) -> BrickModel:
    """1 x 1 bricks for every cell, slopes where ``sites`` say (cells taken once)."""
    used: set[tuple[int, int, int]] = set()
    parts: list[PlacedPart] = []
    for site in sites:
        cells = {(x, y, site.layer) for x, y in site.columns}
        below = {(x, y, site.layer - 1) for x, y in site.sloped}
        if cells & used or below & used:
            continue
        used |= cells | {(x, y, site.layer + 1) for x, y in site.sloped}
        parts.append(
            PlacedPart(
                site.part,
                RED,
                0,
                0,
                3 * site.layer,
                0,
                tuple(
                    (x, y, 3 * site.layer + k)
                    for x, y in site.columns
                    for k in range(3)
                ),
                0,
                "slope",
                studs=site.studs,
            )
        )
    for x, y, z in (tuple(int(v) for v in c) for c in np.argwhere(occupancy)):
        if (x, y, z) not in used:
            cells = tuple((x, y, 3 * z + k) for k in range(3))
            parts.append(PlacedPart("3005", RED, x, y, 3 * z, 0, cells, 0))
    return BrickModel("m", tuple(parts), (BuildStep(),))


@pytest.mark.parametrize(
    "mesh",
    [_ramp(45.0), _ramp(30.0), trimesh.creation.icosphere(subdivisions=4, radius=80)],
    ids=["ramp-45", "ramp-30", "dome"],
)
def test_slopes_bring_the_model_closer_to_the_mesh(mesh: trimesh.Trimesh) -> None:
    occupancy, gains, lattice = _rate(mesh)
    sites = slope_sites(gains)
    assert sites
    stairs = _wedge_model(occupancy, [])
    sloped = _wedge_model(occupancy, sites)
    assert sum(p.category == "slope" for p in sloped.parts) > 0
    vertices = np.asarray(mesh.vertices) - np.asarray(lattice.origin)
    faces = np.asarray(mesh.faces)
    before = surface_deviation(stairs, vertices, faces)
    after = surface_deviation(sloped, vertices, faces)
    assert after.mean_mm < 0.9 * before.mean_mm
    assert after.p95_mm < before.p95_mm


# ------------------------------------------------------------------ grids and files
def _settings(*items: str) -> Settings:
    return load_settings(None, ["input.scale_mode=mm", "input.mm_per_stud=8", *items])


def _model(mesh: trimesh.Trimesh) -> MeshModel:
    return MeshModel(
        mesh=mesh, source=Path("m.stl"), part_names=("m",), watertight=True
    )


def test_voxelize_rates_slopes_and_files_keep_them(tmp_path: Path) -> None:
    grid = voxelize(_model(_ramp(45.0)), _settings()).grid
    assert grid.slopes is not None
    assert grid.slopes.shape == (*grid.shape, 4, 2)
    assert np.isfinite(grid.slopes).any()
    loaded = load_npz(save_npz(grid, tmp_path / "g.grid.npz"))
    assert loaded == grid
    assert loaded.slopes is not None
    shell = hollow(grid, 2)  # the wall placement keeps: every stud cell stays
    assert shell.slopes is not None
    assert np.isfinite(shell.slopes).sum() == np.isfinite(grid.slopes).sum()


@pytest.mark.parametrize(
    "items",
    [
        ["parts.slopes=preserve"],
        ["parts.slopes=smooth"],
        ["parts.categories=[brick, plate, tile]"],
        ["voxel.height_unit=plate"],
    ],
)
def test_no_rating_when_slopes_are_not_wanted(items: list[str]) -> None:
    assert voxelize(_model(_ramp(45.0)), _settings(*items)).grid.slopes is None


def test_grids_check_their_slope_ratings() -> None:
    occupancy = np.zeros((2, 1, 1), dtype=bool)
    occupancy[0] = True
    color = np.where(occupancy, RED, -1).astype(np.int32)
    gains = np.full((2, 1, 1, 4, 2), np.nan, dtype=np.float32)
    gains[1, 0, 0, 0, 0] = 1.0  # an empty stud cell
    with pytest.raises(ValueError, match="slopes marks cells"):
        VoxelGrid(occupancy=occupancy, color=color, slopes=gains)
    with pytest.raises(ValueError, match="slopes must have the shape"):
        VoxelGrid(occupancy=occupancy, color=color, slopes=gains[..., :1])


# ------------------------------------------------------------------ choice
def _gains(*entries: tuple[int, int, int, int, int, float]) -> np.ndarray:
    gains = np.full((6, 6, 3, 4, 2), np.nan, dtype=np.float32)
    for x, y, z, d, k, value in entries:
        gains[x, y, z, d, k] = value
    return gains


def test_two_45_degree_slopes_side_by_side_become_a_2x2_first() -> None:
    sites = slope_sites(_gains((1, 1, 0, PLUS_X, 0, 2.0), (1, 2, 0, PLUS_X, 0, 1.5)))
    assert [s.part for s in sites] == ["3039", "3040b", "3040b"]
    pair = sites[0]
    assert pair.studs == ((1, 1), (1, 2))
    assert pair.sloped == ((2, 1), (2, 2))
    assert pair.gain == pytest.approx(3.5)


def test_33_degree_slopes_run_over_two_columns_and_small_gains_are_dropped() -> None:
    sites = slope_sites(
        _gains((3, 3, 1, MINUS_Y, 1, 1.0), (0, 0, 0, PLUS_Y, 0, 0.2)), min_gain=0.5
    )
    assert len(sites) == 1
    site = sites[0]
    assert site.part == SLOPE_PARTS[2, 1] == "4286"
    assert site.sloped == ((3, 2), (3, 1))
    assert site.gain == pytest.approx(2.0)
    assert site.columns == {(3, 3), (3, 2), (3, 1)}


# ------------------------------------------------------------------ the backend pass
def _layout_with(*bricks: tuple[str, int, int, int, int], colour: int = RED) -> Any:
    from legolization.layout import Layout  # noqa: PLC0415

    layout = Layout(catalog=restricted_catalog(frozenset(_PARTS)))
    for key, x, y, layer, yaw in bricks:
        layout.add(key, x, y, layer, yaw, colour)
    return layout


def _site(
    studs: tuple[tuple[int, int], ...],
    direction: tuple[int, int],
    layer: int = 1,
    run: int = 1,
) -> SlopeSite:
    dx, dy = direction
    sloped = tuple(
        (x + dx * step, y + dy * step) for step in range(1, run + 1) for x, y in studs
    )
    part = SLOPE_PARTS[run, len(studs)]
    return SlopeSite(studs, sloped, layer, direction, part, 1.0)


def _parts(layout: Any) -> Counter[str]:
    return Counter(layout.part_of(b).ldraw_part for b in layout)


def _slope(layout: Any) -> Any:
    return next(b for b in layout if layout.part_of(b).category.value == "slope")


def _studs(layout: Any, brick: Any) -> set[tuple[int, int]]:
    return {(c.cell[0], c.cell[1]) for c in layout.connectors_of(brick, top=True)}


def test_a_slope_cuts_the_edge_off_a_stair() -> None:
    layout = _layout_with(("brick_2x2", 0, 0, 0, 0), ("brick_1x2", 0, 0, 3, 0))
    report = apply_slopes(layout, [_site(((0, 0),), (1, 0))])
    assert (report.count, report.cut, report.filled, report.added) == (1, 1, 0, 0)
    assert _parts(layout) == {"3003": 1, "3040b": 1}
    slope = _slope(layout)
    assert _studs(layout, slope) == {(0, 0)}
    assert {(x, y) for x, y, _ in layout.cells_of(slope)} == {(0, 0), (1, 0)}


def test_a_slope_fills_the_corner_of_a_stair() -> None:
    layout = _layout_with(("brick_2x2", 0, 0, 0, 0), ("brick_1x1", 0, 0, 3, 0))
    report = apply_slopes(layout, [_site(((0, 0),), (1, 0))])
    assert (report.count, report.cut, report.filled) == (1, 0, 1)
    assert _parts(layout) == {"3003": 1, "3040b": 1}
    assert (1, 0, 3) in layout.occupancy  # material beyond the voxels


@pytest.mark.parametrize("direction", [(1, 0), (-1, 0), (0, 1), (0, -1)])
@pytest.mark.parametrize("run", [1, 2])
def test_slopes_fall_every_way(direction: tuple[int, int], run: int) -> None:
    base = [("brick_2x4", x, y, 0, 0) for x in (0, 4) for y in (0, 2, 4, 6)]
    layout = _layout_with(*base, ("brick_1x1", 3, 3, 3, 0))
    report = apply_slopes(layout, [_site(((3, 3),), direction, run=run)])
    assert report.count == 1
    slope = _slope(layout)
    assert _studs(layout, slope) == {(3, 3)}
    dx, dy = direction
    expected = {(3 + dx * step, 3 + dy * step) for step in range(run + 1)}
    assert {(x, y) for x, y, _ in layout.cells_of(slope)} == expected


def test_two_columns_side_by_side_take_a_2x2_slope() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0), ("brick_2x2", 0, 0, 3, 0))
    report = apply_slopes(layout, [_site(((0, 0), (0, 1)), (1, 0))])
    assert report.placed == {"3039": 1}
    assert _parts(layout) == {"3001": 1, "3039": 1}


def test_what_is_left_of_a_cut_brick_becomes_bricks_of_its_colour() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0), ("brick_1x4", 0, 0, 3, 0))
    report = apply_slopes(layout, [_site(((2, 0),), (1, 0))])
    assert (report.count, report.added) == (1, 1)
    assert _parts(layout) == {"3001": 1, "3040b": 1, "3004": 1}
    rest = next(b for b in layout if layout.part_of(b).ldraw_part == "3004")
    assert rest.colour_code == RED
    assert {(x, y) for x, y, _ in layout.cells_of(rest)} == {(0, 0), (1, 0)}


def test_slopes_that_would_add_too_many_parts_stay_stairs() -> None:
    # A slope in the middle of a 1 x 6 brick leaves two pieces: +2 parts.
    def layout() -> Any:
        return _layout_with(
            ("brick_2x4", 0, 0, 0, 0), ("brick_2x4", 4, 0, 0, 0),
            ("brick_1x6", 0, 0, 3, 0),
        )  # fmt: skip

    site = [_site(((2, 0),), (0, 1))]
    cheap = layout()
    report = apply_slopes(cheap, site, max_cost=1)
    assert (report.count, report.costly) == (0, 1)
    assert "would add more than 1 parts" in report.summary()
    dear = layout()
    report = apply_slopes(dear, site, max_cost=2)
    assert (report.count, report.added) == (1, 2)


def test_a_parts_limit_keeps_the_best_slopes() -> None:
    def layout() -> Any:
        return _layout_with(
            ("brick_2x4", 0, 0, 0, 0), ("brick_1x4", 0, 0, 3, 0),
            ("brick_2x4", 0, 2, 0, 0), ("brick_1x4", 0, 2, 3, 0),
        )  # fmt: skip

    # Each slope at the end of a 1 x 4 brick adds one part (the 1 x 2 left).
    sites = [_site(((2, 0),), (1, 0)), _site(((2, 2),), (1, 0))]
    free = layout()
    assert apply_slopes(free, sites).count == 2
    limited = layout()
    report = apply_slopes(limited, sites, max_added=1)
    assert (report.count, report.limited) == (1, 1)
    assert "parts limit reached" in report.summary()
    assert _studs(limited, _slope(limited)) == {(2, 0)}  # the first, best one


def test_the_part_estimate_counts_the_slopes() -> None:
    from mesh2brick.voxel.estimate import (  # noqa: PLC0415
        SLOPE_PARTS_PER_CELL,
        parts_estimate,
    )

    grid = voxelize(_model(_ramp(45.0)), _settings()).grid
    assert grid.slopes is not None
    worth = rating.worth_a_slope(grid.slopes)
    assert worth > 0
    plain = parts_estimate(_copy(grid, slopes=None))
    sloped = parts_estimate(grid)
    assert sloped.expected == round(plain.expected + SLOPE_PARTS_PER_CELL[1] * worth)
    assert sloped.high > plain.high
    capped = parts_estimate(grid, slopes_max_share=0.0)
    assert (capped.low, capped.expected, capped.high) == (
        plain.low,
        plain.expected,
        plain.high,
    )


def _copy(grid: VoxelGrid, **changes: Any) -> VoxelGrid:
    import dataclasses  # noqa: PLC0415

    return dataclasses.replace(grid, **changes)


def test_the_parts_limit_is_a_setting() -> None:
    assert _settings().parts.slopes_max_share is None
    assert _settings("parts.slopes_max_share=0.15").parts.slopes_max_share == 0.15
    with pytest.raises(ValueError, match="slopes_max_share"):
        _settings("parts.slopes_max_share=-1")


def test_pieces_join_their_neighbours_again() -> None:
    from mesh2brick.backends.slopes import _merge_pieces  # noqa: PLC0415

    layout = _layout_with(("brick_1x2", 0, 0, 0, 0), ("brick_1x2", 2, 0, 0, 0))
    first = min(b.brick_id for b in layout)
    saved = _merge_pieces(layout, {first}, allowed=None, produced=lambda *_: None)
    assert saved == 1
    assert _parts(layout) == {"3010": 1}  # 1 x 4
    other = _layout_with(("brick_1x2", 0, 0, 0, 0))
    other.add("brick_1x2", 2, 0, 0, 0, 1)  # blue
    first = min(b.brick_id for b in other)
    assert _merge_pieces(other, {first}, allowed=None, produced=lambda *_: None) == 0


def test_slopes_lego_does_not_make_in_the_colour_stay_stairs() -> None:
    layout = _layout_with(("brick_2x2", 0, 0, 0, 0), ("brick_1x2", 0, 0, 3, 0))
    before = dict(layout.bricks)

    def produced(part: str, colour: int) -> bool | None:
        return False if part.startswith(("3040", "3039")) else None

    report = apply_slopes(layout, [_site(((0, 0),), (1, 0))], produced=produced)
    assert report.count == 0
    assert report.colour == {RED: 1}
    assert report.missing == {RED: ("3040b",)}
    assert "for want of the colour" in report.summary()
    assert layout.bricks == before


def test_a_slope_is_used_where_its_colour_exists() -> None:
    # A 3039 is not made in the colour, two 3040b are: they take its place.
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0), ("brick_2x2", 0, 0, 3, 0))
    sites = [
        _site(((0, 0), (0, 1)), (1, 0)),
        _site(((0, 0),), (1, 0)),
        _site(((0, 1),), (1, 0)),
    ]

    def produced(part: str, colour: int) -> bool | None:
        return part != "3039"

    report = apply_slopes(layout, sites, produced=produced)
    assert report.placed == {"3040b": 2}
    assert report.colour == {}  # every stair got a slope after all


@pytest.mark.parametrize(
    "extra",
    [
        ("plate_1x1", 1, 0, 6, 0),  # something rests on the sloped column
        ("tile_1x1", 0, 0, 5, 0),  # a tile on the stud column (another family)
    ],
)
def test_sites_that_do_not_fit_stay_stairs(
    extra: tuple[str, int, int, int, int],
) -> None:
    key, x, y, layer, yaw = extra
    bricks = [("brick_2x2", 0, 0, 0, 0)]
    if key == "tile_1x1":
        bricks += [("plate_1x2", 0, 0, 3, 0), ("plate_1x2", 0, 0, 4, 0)]
        bricks += [("plate_1x1", 1, 0, 5, 0)]
    else:
        bricks += [("brick_1x2", 0, 0, 3, 0)]
    layout = _layout_with(*bricks, (key, x, y, layer, yaw))
    before = dict(layout.bricks)
    report = apply_slopes(layout, [_site(((0, 0),), (1, 0))])
    assert report.count == 0
    assert layout.bricks == before


def test_a_slope_never_splits_the_model() -> None:
    # The top 1 x 2 brick (x 0..1) holds a 1 x 1 brick at (1, 0) on top of it
    # (layer 2) and stands on a 2 x 2. A slope at (0, 0) -> (1, 0) would cut
    # (1, 0) loose: blocked because something rests on the sloped column.
    # Instead: a column whose only link to the rest is the cut part.
    layout = _layout_with(
        ("brick_1x1", 0, 0, 0, 0),  # holds the stud column from below
        ("brick_1x1", 2, 0, 0, 0),  # an island once the 1 x 3 above is cut
        ("brick_1x3", 0, 0, 3, 0),  # x 0..2 at layer 1
    )
    report = apply_slopes(layout, [_site(((1, 0),), (-1, 0))])
    assert report.count == 0
    assert _parts(layout) == {"3005": 2, "3622": 1}


def test_parts_outside_the_whitelist_are_not_used() -> None:
    layout = _layout_with(("brick_2x2", 0, 0, 0, 0), ("brick_1x2", 0, 0, 3, 0))
    report = apply_slopes(layout, [_site(((0, 0),), (1, 0))], slopes=frozenset())
    assert report.count == 0
    other = _layout_with(("brick_2x4", 0, 0, 0, 0), ("brick_1x4", 0, 0, 3, 0))
    pieces = frozenset(_PARTS) - {"3004", "3005"}  # nothing for the rest
    report = apply_slopes(other, [_site(((2, 0),), (1, 0))], allowed=pieces)
    assert report.count == 0


def test_slopes_left_out_of_placement_for_their_colour_come_back() -> None:
    # parts.availability=exclude drops a slope from the placement catalogue
    # if one model colour lacks it; the pass checks each slope's colour.
    from legolization.layout import Layout  # noqa: PLC0415

    no_slopes = frozenset(_PARTS) - {"3040b", "3039", "4286"}
    layout = Layout(catalog=restricted_catalog(no_slopes))
    layout.add("brick_2x2", 0, 0, 0, 0, RED)
    layout.add("brick_1x2", 0, 0, 3, 0, RED)
    assert "3040b" not in {p.ldraw_part for p in layout.catalog.parts.values()}
    report = apply_slopes(layout, [_site(((0, 0),), (1, 0))], allowed=no_slopes)
    assert report.placed == {"3040b": 1}
    assert with_slopes(layout.catalog) is layout.catalog  # added once


def test_slopes_are_drawn_with_studs_on_their_high_row() -> None:
    layout = _layout_with(("brick_2x2", 0, 0, 0, 0), ("brick_1x2", 0, 0, 3, 0))
    apply_slopes(layout, [_site(((0, 0),), (1, 0))])
    model = to_brick_model(layout, None, name="m")
    slope = next(p for p in model.parts if p.category == "slope")
    assert slope.top_studs == frozenset({(0, 0)})


def test_the_report_names_what_happened() -> None:
    report = SlopeReport(
        placed={"3039": 2, "3040b": 3}, cut=4, filled=3, added=2, colour={RED: 1},
        missing={RED: ("3039",)},
    )  # fmt: skip
    text = report.summary()
    assert text.startswith("slopes on tilted stairs: 5 (2 x 3039, 3 x 3040b)")
    assert "+2 parts" in text
    assert "3 sloped column(s) fill a stair corner" in text
    assert "3039 not in colour 4 (Red)" in text


# ------------------------------------------------------------------ whole runs
def _ramp_grid() -> VoxelGrid:
    return voxelize(_model(_ramp(40.0, length=48.0)), _settings()).grid


@pytest.mark.ldraw
def test_a_ramp_gets_slopes_and_stays_one_stable_piece(tmp_path: Path) -> None:
    grid = _ramp_grid()
    backend = LegolizationBackend()
    placement = backend.place(grid, _settings(), name="ramp")
    slopes = [p for p in placement.model.parts if p.category == "slope"]
    assert slopes
    assert placement.stability.buildable
    assert any(n.startswith("slopes on tilted stairs") for n in placement.notes)
    path = backend.write_ldraw(placement, tmp_path / "ramp.mpd")
    assert backend.verify_ldraw(path) == placement.model.part_count
    plain = backend.place(grid, _settings("parts.slopes=preserve"), name="ramp")
    assert len([p for p in plain.model.parts if p.category == "slope"]) < len(slopes)
    assert not any(n.startswith("slopes on tilted") for n in plain.notes)


@pytest.mark.ldraw
def test_slopes_are_undone_when_the_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dataclasses  # noqa: PLC0415
    import threading  # noqa: PLC0415

    from mesh2brick.backends import legolization  # noqa: PLC0415

    real = legolization._report

    def failing_check(layout: Any, result: Any) -> Any:
        report = real(layout, result)
        if threading.current_thread().name.startswith("finish-check"):
            return dataclasses.replace(report, stable=False)
        return report

    monkeypatch.setattr(legolization, "_report", failing_check)
    placement = LegolizationBackend().place(_ramp_grid(), _settings(), name="ramp")
    plain = LegolizationBackend().place(
        _ramp_grid(), _settings("parts.slopes=preserve"), name="ramp"
    )
    assert placement.stability.buildable
    assert any(n.startswith("slopes undone") for n in placement.notes)
    assert not any(n.startswith("slopes on tilted") for n in placement.notes)
    assert Counter(p.part for p in placement.model.parts) == Counter(
        p.part for p in plain.model.parts
    )


def test_without_time_for_a_check_slopes_are_skipped() -> None:
    import time  # noqa: PLC0415

    from mesh2brick.backends.protocols import StabilityReport  # noqa: PLC0415

    layout = _layout_with(("brick_2x2", 0, 0, 0, 0), ("brick_1x2", 0, 0, 3, 0))
    gains = np.full((2, 2, 2, 4, 2), np.nan, dtype=np.float32)
    gains[0, 0, 1, PLUS_X, 0] = 2.0
    occupancy = np.zeros((2, 2, 2), dtype=bool)
    occupancy[:, :, 0] = True
    occupancy[:, 0, 1] = True
    grid = VoxelGrid(
        occupancy=occupancy,
        color=np.where(occupancy, RED, -1).astype(np.int32),
        slopes=gains,
    )
    stable = StabilityReport(
        stable=True, component_count=1, floating_count=0, max_score=0.1
    )
    backend = LegolizationBackend()
    kwargs: dict[str, Any] = {
        "settings": _settings(),
        "allowed": Whitelist(frozenset(_PARTS)),
        "slopes": frozenset(_PARTS),
        "stability": stable,
    }
    late = backend._slope_stairs(
        layout, grid, deadline=time.monotonic() - 1.0, **kwargs
    )
    assert late.skipped
    assert late.before is None
    assert late.notes[0].startswith("slopes skipped: time limit")
    assert _parts(layout) == {"3003": 1, "3004": 1}
    done = backend._slope_stairs(layout, grid, deadline=None, **kwargs)
    assert not done.skipped
    assert done.before is not None
    assert _parts(layout) == {"3003": 1, "3040b": 1}


def test_skipped_slopes_are_marked_on_the_cover(tmp_path: Path) -> None:
    from mesh2brick.render.pdf import _cover_notes  # noqa: PLC0415

    model = BrickModel(
        name="m",
        parts=(make_brick("3001", 0, 0, 0, 0),),
        steps=(BuildStep(),),
        slopes_skipped=True,
    )
    again = BrickModel.load(model.save(tmp_path / "m.bricks.json"))
    assert again.slopes_skipped
    notes = [note for note, _ in _cover_notes(again, "de")]
    assert "Dachsteine übersprungen: Zeitgrenze; empfohlen --time 10min." in notes
    english = [note for note, _ in _cover_notes(again, "en")]
    assert "Slopes skipped: time limit; recommended --time 10min." in english
