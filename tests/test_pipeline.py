# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""SPEC Phase 2: `convert` end to end (LDraw + 3 BOMs + PDF)."""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path

import numpy as np
import pytest
import trimesh

from mesh2brick.backends.legolization import LegolizationBackend
from mesh2brick.catalog.rebrickable import catalogue_colors
from mesh2brick.config import load_settings
from mesh2brick.pipeline import convert, palette_for
from mesh2brick.voxel.voxelize import remove_islands

pytestmark = pytest.mark.ldraw


@pytest.fixture(scope="module")
def bunny(fixtures_dir: Path, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    out = tmp_path_factory.mktemp("bunny")
    settings = load_settings(None, ["input.target_studs=12", f"output.dir={out}"])
    return convert(fixtures_dir / "bunny_lowpoly.stl", settings), out


def test_acceptance_convert_bunny(bunny) -> None:  # type: ignore[no-untyped-def]
    """PDF opens, steps complete, BOM total = part count = parts in the .mpd."""
    result, out = bunny
    names = {p.name for p in result.files}
    assert names >= {
        "bunny_lowpoly.grid.npz",
        "bunny_lowpoly.mpd",
        "bunny_lowpoly.bricks.json",
        "bunny_lowpoly.bom.csv",
        "bunny_lowpoly.bricklink.xml",
        "bunny_lowpoly.rebrickable.csv",
        "bunny_lowpoly.pdf",
        "bunny_lowpoly.png",
    }
    model = result.model
    lines = (out / "bunny_lowpoly.mpd").read_text().splitlines()
    ldr_parts = [line for line in lines if line.startswith("1 ") and ".dat" in line]
    with (out / "bunny_lowpoly.bom.csv").open() as handle:
        bom_total = sum(int(row["quantity"]) for row in csv.DictReader(handle))
    assert bom_total == result.bom.total == model.part_count == len(ldr_parts)
    # Stand-in for opening it in LDView/Studio: strict re-import.
    assert LegolizationBackend().verify_ldraw(out / "bunny_lowpoly.mpd") == len(
        ldr_parts
    )
    # Sub-assemblies are LDraw sub-models with their own steps (SPEC Phase 6).
    files = [line for line in lines if line.startswith("0 FILE ")]
    assert len(files) == 1 + len(model.submodels)
    # Every part sits in exactly one step; only attach steps are part-free.
    assert sorted(p.step for p in model.parts) == sorted(
        p.step for p in model.parts if 0 <= p.step < model.step_count
    )
    pdf = (out / "bunny_lowpoly.pdf").read_bytes()
    assert pdf.startswith(b"%PDF")
    pages = len(re.findall(rb"/Type /Page[^s]", pdf))
    assert pages == 2 + math.ceil(model.step_count / 2)  # cover, parts, 2 per page
    assert len(pdf) < 10_000_000  # SPEC Phase 6
    assert result.stability.component_count == 1
    assert set(result.seconds) >= {"voxelize", "place", "export", "instructions"}


def test_convert_from_grid_file(bunny, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _, out = bunny
    settings = load_settings(
        None, [f"output.dir={tmp_path}", "output.formats=[mpd, bom_csv]"]
    )
    result = convert(out / "bunny_lowpoly.grid.npz", settings, name="again")
    names = {p.name for p in result.files}
    assert {"again.mpd", "again.bom.csv"} <= names
    assert "again.pdf" not in names


def test_convert_rejects_bad_input(tmp_path: Path) -> None:
    path = tmp_path / "model.fbx"
    path.write_text("Kaydara FBX Binary")
    with pytest.raises(ValueError, match="unsupported input format"):
        convert(path, load_settings(None, [f"output.dir={tmp_path}"]))


def test_convert_rejects_tiny_models(fixtures_dir: Path, tmp_path: Path) -> None:
    settings = load_settings(
        None,
        ["input.scale_mode=mm", "input.mm_per_stud=40", f"output.dir={tmp_path}"],
    )
    with pytest.raises(ValueError, match="no cells"):
        convert(fixtures_dir / "cube_10mm.stl", settings)


def test_large_models_get_held_parts_and_even_steps(bunny, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Layer-order steps (big models): nothing hangs in the air, sizes stay even."""
    from mesh2brick.steps.metrics import step_stats  # noqa: PLC0415
    from mesh2brick.voxel.io import load_npz  # noqa: PLC0415

    _, out = bunny
    settings = load_settings(None, ["steps.sequencing=layers"])
    placement = LegolizationBackend().place(
        load_npz(out / "bunny_lowpoly.grid.npz"), settings, name="b"
    )
    model = placement.model
    stats = step_stats(model)
    assert stats.hanging == 0
    assert stats.largest <= settings.steps.parts_per_step + 3
    assert all(step.stable is None for step in model.steps)  # not checked
    path = LegolizationBackend().write_ldraw(placement, tmp_path / "b.ldr")
    assert LegolizationBackend().verify_ldraw(path) == model.part_count


# ------------------------------------------------------------------ islands
def test_remove_islands_drops_small_and_keeps_big() -> None:
    occupancy = np.zeros((30, 3, 3), dtype=bool)
    occupancy[0:20] = True  # 180 cells
    occupancy[22, 1, 1] = True  # 1 cell island
    occupancy[25:30] = True  # 45-cell island (20 %)
    cleaned, notes = remove_islands(occupancy, min_fraction=0.05)
    assert not cleaned[22, 1, 1]
    assert cleaned[25:30].all()
    assert "removed 1 loose voxel island" in notes[0]
    assert "2 separate pieces" in notes[1]
    kept, none_removed = remove_islands(occupancy, min_fraction=0.0)
    assert kept[22, 1, 1]
    assert "3 separate pieces" in none_removed[0]


def test_single_piece_has_no_notes() -> None:
    cleaned, notes = remove_islands(np.ones((2, 2, 2), dtype=bool), min_fraction=0.05)
    assert cleaned.all()
    assert notes == []


def test_voxelize_removes_a_loose_speck(tmp_path: Path) -> None:
    from mesh2brick.ingest import load_model  # noqa: PLC0415
    from mesh2brick.voxel.voxelize import voxelize  # noqa: PLC0415

    body = trimesh.creation.box(extents=(40, 40, 40))
    speck = trimesh.creation.box(extents=(3, 3, 3))
    speck.apply_translation((30, 0, 0))
    path = tmp_path / "speck.stl"
    trimesh.util.concatenate([body, speck]).export(path)
    settings = load_settings(None, ["input.scale_mode=mm", "input.mm_per_stud=2"])
    result = voxelize(load_model(path, settings.input), settings)
    assert any("removed 1 loose voxel island" in w for w in result.warnings)


# ------------------------------------------------------------------ colours
def test_acceptance_coloured_obj_gives_multicolour_model(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    """SPEC Phase 3: a coloured OBJ fixture yields a multi-coloured model."""
    settings = load_settings(
        None,
        [
            "input.target_studs=12",
            f"output.dir={tmp_path}",
            "output.formats=[ldr, bom_csv]",
        ],
    )
    result = convert(fixtures_dir / "toadstool.obj", settings)
    names = {info.name for info in result.model.colors.values()}
    assert {"Red", "White"} <= names
    with (tmp_path / "toadstool.bom.csv").open() as handle:
        colours = {row["color_name"] for row in csv.DictReader(handle)}
    assert {"Red", "White"} <= colours
    assert LegolizationBackend().verify_ldraw(tmp_path / "toadstool.ldr") == (
        result.model.part_count
    )


def test_palette_follows_the_setting() -> None:
    from mesh2brick.catalog.rebrickable import common_colors  # noqa: PLC0415

    salmon = np.array([[249, 153, 99]], dtype=np.uint8)  # Duo's "Mandarin Orange"
    common = palette_for(load_settings(None, []))
    solid = palette_for(load_settings(None, ["color.palette=solid"]))
    every = palette_for(load_settings(None, ["color.palette=all"]))
    assert int(common(salmon)[0]) in common_colors()
    assert int(solid(salmon)[0]) in catalogue_colors()
    assert every(salmon)[0] >= 0
    assert len(common_colors()) == 42  # today's palette, no Flat Silver
    # incl. Coral, Olive Green and Dark Purple (LDraw: Medium Lilac, renamed)
    assert {0, 4, 15, 71, 72, 353, 330, 85} <= common_colors()
    assert not {7, 8, 6, 225, 315} & common_colors()  # old/rare, Flat Silver
    assert 315 not in catalogue_colors()
