# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Tiles on flat tops: the backend pass, stability and output (ROADMAP 9)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mesh2brick.backends.legolization import (
    LegolizationBackend,
    apply_tiles,
    placeable_parts,
    placement_footprint,
    restricted_catalog,
)
from mesh2brick.config import load_settings
from mesh2brick.export.bom import build_bom, write_boms
from mesh2brick.model import BrickModel
from mesh2brick.place.tiles import flat_top_plates
from mesh2brick.render.preview import PreviewOptions, render_png
from mesh2brick.render.text import part_label
from mesh2brick.voxel.grid import VoxelGrid

RED = 4
TILES = ("3070b", "3069b", "63864", "2431", "6636", "4162", "3068b", "87079", "69729")
"""Every tile legolization's catalogue has (four placeable, five import-only)."""
_PARTS = (
    "3005", "3004", "3010", "3003", "3002", "3001", "3024", "3023", "3710",
    "3022", "3021", "3020", *TILES,
)  # fmt: skip


def _layout_with(*bricks: tuple[str, int, int, int, int]) -> Any:
    from legolization.layout import Layout  # noqa: PLC0415

    layout = Layout(catalog=restricted_catalog(frozenset(_PARTS)))
    for key, x, y, layer, yaw in bricks:
        layout.add(key, x, y, layer, yaw, RED)
    return layout


def _flat(
    *boxes: tuple[int, int, int, int, int], rise: float = 0.0
) -> dict[tuple[int, int, int], float]:
    """Plate cells ``x0..x1 x y0..y1`` at ``layer``, the face ``rise`` plates up."""
    return {
        (x, y, layer): rise
        for x0, x1, y0, y1, layer in boxes
        for x in range(x0, x1)
        for y in range(y0, y1)
    }


def _parts(layout: Any) -> Counter[str]:
    return Counter(layout.part_of(b).ldraw_part for b in layout)


# ------------------------------------------------------------------ the pass
def test_open_plates_become_tiles_of_the_same_size() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0), ("plate_2x4", 0, 0, 3, 0))
    cells = set(layout.occupancy)
    report = apply_tiles(layout, _flat((0, 4, 0, 2, 3)))
    assert (report.plates, report.bricks, report.added) == (1, 0, 0)
    assert _parts(layout) == {"3001": 1, "87079": 1}  # 2 x 4 tile, import-only
    assert set(layout.occupancy) == cells


def test_open_bricks_become_two_plates_and_a_tile() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0))
    report = apply_tiles(layout, _flat((0, 4, 0, 2, 2)))
    assert (report.bricks, report.added, report.heavier) == (1, 2, True)
    assert _parts(layout) == {"3020": 2, "87079": 1}
    by_layer = {b.layer: layout.part_of(b).ldraw_part for b in layout}
    assert by_layer == {0: "3020", 1: "3020", 2: "87079"}


def test_a_face_a_plate_lower_takes_one_plate_and_a_tile() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0))
    report = apply_tiles(layout, _flat((0, 4, 0, 2, 2), rise=-0.9))
    assert (report.lowered, report.added, report.heavier) == (1, 1, False)
    by_layer = {b.layer: layout.part_of(b).ldraw_part for b in layout}
    assert by_layer == {0: "3020", 1: "87079"}  # the top is one plate lower


def test_a_face_a_plate_higher_gets_a_tile_on_the_part() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0), ("plate_2x4", 0, 0, 3, 0))
    report = apply_tiles(layout, _flat((0, 4, 0, 2, 3), rise=0.7))
    assert (report.topped, report.added, report.heavier) == (1, 1, True)
    by_layer = {b.layer: layout.part_of(b).ldraw_part for b in layout}
    assert by_layer == {0: "3001", 3: "3020", 4: "87079"}


def test_a_plate_never_goes_lower() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0), ("plate_2x4", 0, 0, 3, 0))
    report = apply_tiles(layout, _flat((0, 4, 0, 2, 3), rise=-1.0))
    assert (report.plates, report.heavier) == (1, False)
    by_layer = {b.layer: layout.part_of(b).ldraw_part for b in layout}
    assert by_layer == {0: "3001", 3: "87079"}


def test_tops_outside_the_mask_or_covered_keep_their_studs() -> None:
    layout = _layout_with(
        ("brick_2x4", 0, 0, 0, 0),
        ("brick_2x4", 0, 2, 0, 0),
        ("plate_1x2", 0, 2, 3, 0),  # sits on the second brick
    )
    # First brick only half in the mask, second covered, the 1 x 2 not flat.
    report = apply_tiles(layout, _flat((0, 2, 0, 2, 2), (0, 4, 2, 4, 2)))
    assert report.tiled == 0
    assert _parts(layout) == {"3001": 2, "3023": 1}


def test_sizes_without_a_tile_are_covered_by_several() -> None:
    layout = _layout_with(("brick_2x3", 0, 0, 0, 0), ("plate_2x3", 0, 0, 3, 0))
    report = apply_tiles(layout, _flat((0, 3, 0, 2, 3)))
    assert (report.split_plates, report.added) == (1, 1)
    assert _parts(layout) == {"3002": 1, "3068b": 1, "3069b": 1}


def test_a_split_tile_needs_something_below() -> None:
    # A 2 x 3 plate held at one end: its 2 x 2 part would rest on nothing.
    layout = _layout_with(("brick_1x2", 0, 0, 0, 90), ("plate_2x3", 0, 0, 3, 0))
    cover = layout.cells_of(next(b for b in layout if b.layer == 3))
    assert {c[0] for c in cover} == {0, 1, 2}
    report = apply_tiles(layout, _flat((0, 3, 0, 2, 3)))
    assert report.tiled == 0
    assert report.kept == 1


def test_colours_lego_does_not_make_keep_the_studs() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0), ("plate_2x4", 0, 0, 3, 0))
    report = apply_tiles(
        layout,
        _flat((0, 4, 0, 2, 3)),
        produced=lambda part, _colour: part != "87079",
    )
    # No 2 x 4 tile in red: two 2 x 2 tiles instead (both rest on the brick).
    assert report.split_plates == 1
    assert _parts(layout)["3068b"] == 2


def test_whitelists_limit_the_tiles() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0), ("plate_2x4", 0, 0, 3, 0))
    allowed = frozenset({"3001", "3020", "3070b"})
    report = apply_tiles(layout, _flat((0, 4, 0, 2, 3)), allowed=allowed)
    assert report.split_plates == 1
    assert _parts(layout) == {"3001": 1, "3070b": 8}


def test_the_base_layer_can_be_left_alone() -> None:
    layout = _layout_with(("brick_2x4", 0, 0, 0, 0))
    report = apply_tiles(layout, _flat((0, 4, 0, 2, 2)), base=False)
    assert report.tiled == 0


def test_finishing_tiles_are_placeable_tiles() -> None:
    tiles = {p.part for p in placeable_parts() if p.category == "tile"}
    assert tiles == set(TILES)
    assert placement_footprint("87079") == (2, 4, 1)
    assert placement_footprint("69729") == (2, 6, 1)


# ------------------------------------------------------------------ end to end
def _box_grid(width: int, depth: int, height: int, rise: float = 0.0) -> VoxelGrid:
    occupancy = np.ones((width, depth, height), dtype=bool)
    flat = np.full(occupancy.shape, np.nan, dtype=np.float32)
    flat[:, :, -1] = rise
    return VoxelGrid(
        occupancy=occupancy,
        color=np.where(occupancy, RED, -1).astype(np.int32),
        flat=flat,
    )


@pytest.fixture(scope="module")
def tiled_box(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Path]:
    settings = load_settings(None, ["parts.categories=[brick, plate, tile]"])
    backend = LegolizationBackend()
    placement = backend.place(_box_grid(6, 4, 2), settings, name="box")
    path = backend.write_ldraw(placement, tmp_path_factory.mktemp("box") / "box.mpd")
    return placement, path


@pytest.mark.ldraw
def test_a_box_gets_a_smooth_top_and_stays_one_stable_piece(
    tiled_box: tuple[Any, Path],
) -> None:
    placement, path = tiled_box
    model: BrickModel = placement.model
    top = max(c[2] for p in model.parts for c in p.cells)
    roof = [p for p in model.parts if any(c[2] == top for c in p.cells)]
    assert roof
    assert all(p.category == "tile" for p in roof)
    assert placement.stability.buildable
    assert any(note.startswith("tiles on flat tops") for note in placement.notes)
    assert LegolizationBackend().verify_ldraw(path) == model.part_count


@pytest.mark.ldraw
def test_without_tile_in_categories_nothing_changes() -> None:
    grid = _box_grid(6, 4, 2)
    backend = LegolizationBackend()
    plain = backend.place(grid, load_settings(None, []), name="box")
    assert not any(p.category == "tile" for p in plain.model.parts)
    assert not any("tile" in note for note in plain.notes)
    also = backend.place(grid, load_settings(None, []), name="box")
    assert also.model == plain.model


@pytest.mark.ldraw
def test_tiles_are_drawn_without_studs_and_named_in_parts_lists(
    tiled_box: tuple[Any, Path], tmp_path: Path
) -> None:
    placement, _ = tiled_box
    model: BrickModel = placement.model
    tile = next(p for p in model.parts if p.category == "tile")
    assert tile.top_studs == frozenset()
    assert part_label(tile, "de").startswith("Fliese")
    assert part_label(tile, "en").startswith("Tile")
    bom = build_bom(model)
    lines = [line for line in bom.lines if line.part in TILES]
    assert lines
    assert all(line.on_bricklink and line.on_rebrickable for line in lines)
    assert {line.bricklink_part for line in lines} <= set(TILES)
    files = write_boms(bom, tmp_path, "box", ("bom_bricklink", "bom_rebrickable"))
    text = "".join(path.read_text(encoding="utf-8") for path in files)
    assert all(line.part in text for line in lines)
    assert render_png(model, PreviewOptions(width_px=200, height_px=150))


def test_flat_tops_match_the_grid_layers() -> None:
    grid = _box_grid(2, 2, 2, rise=-1 / 3)
    assert grid.flat is not None
    found = flat_top_plates(grid.flat, grid.plates_per_cell)
    assert found.keys() == {(x, y, 5) for x in range(2) for y in range(2)}
    assert np.allclose(list(found.values()), -1.0)


@pytest.mark.ldraw
def test_tiles_are_undone_when_the_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import dataclasses  # noqa: PLC0415
    import threading  # noqa: PLC0415

    from mesh2brick.backends import legolization  # noqa: PLC0415

    real = legolization._report
    checks: list[str] = []

    def failing_tile_check(layout: Any, result: Any) -> Any:
        report = real(layout, result)
        name = threading.current_thread().name
        if not name.startswith("tile-check"):
            return report
        checks.append(name)
        return dataclasses.replace(report, stable=False)

    monkeypatch.setattr(legolization, "_report", failing_tile_check)
    settings = load_settings(None, ["parts.categories=[brick, plate, tile]"])
    placement = LegolizationBackend().place(_box_grid(6, 4, 2), settings, name="box")
    assert len(checks) == 1  # the check of the tiles, in its own thread
    assert not any(p.category == "tile" for p in placement.model.parts)
    assert placement.stability.buildable
    assert any(note.startswith("tiles undone") for note in placement.notes)
    assert not any(note.startswith("tiles on flat tops") for note in placement.notes)


def test_without_time_for_a_check_only_lighter_changes_are_made() -> None:
    layout = _layout_with(
        ("brick_2x4", 0, 0, 0, 0),  # face a plate lower: plate + tile, lighter
        ("brick_2x4", 0, 2, 0, 0),  # face at the top: 2 plates + tile, heavier
    )
    flat = {**_flat((0, 4, 0, 2, 2), rise=-1.0), **_flat((0, 4, 2, 4, 2))}
    report = apply_tiles(layout, flat, heavier=False)
    assert (report.lowered, report.bricks, report.unchecked) == (1, 0, 1)
    assert not report.heavier
    assert "no time to check" in report.summary()


@pytest.mark.ldraw
def test_the_llm_layer_is_told_what_a_tile_is(tiled_box: tuple[Any, Path]) -> None:
    from mesh2brick.agent.describe import part_kinds  # noqa: PLC0415
    from mesh2brick.agent.prompts import SYSTEM  # noqa: PLC0415

    placement, _ = tiled_box
    kinds = part_kinds(placement.model, "de")
    assert "Fliese" in kinds
    assert "(en: Tile" in kinds
    assert "Fliese" in SYSTEM
    assert "without" in SYSTEM
