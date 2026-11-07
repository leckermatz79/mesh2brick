# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""``mesh2brick inspect``: facts and picture before converting (Phase 8)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from mesh2brick.backends.legolization import color_info
from mesh2brick.cli import app
from mesh2brick.config import load_settings
from mesh2brick.inspection import (
    CELLS_PER_PART,
    PANEL_PX,
    inspect_file,
    inspection_text,
    quick_fill,
    render_inspection,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.ldraw
runner = CliRunner()


def test_coloured_mesh(fixtures_dir: Path) -> None:
    settings = load_settings(None, ["input.target_studs=16"])
    result = inspect_file(fixtures_dir / "toadstool.obj", settings, name="toadstool")
    assert result.model is not None
    assert result.report is not None
    assert 0 < result.shell.filled_count < result.grid.filled_count
    assert result.surface_colors["cad"] == pytest.approx(1.0)
    cells = result.color_cells
    assert sum(n for _, n in cells) == result.shell.filled_count
    assert {code for code, _ in cells} >= {4, 15}  # red cap, white spots
    low, expected, high = result.parts_estimate
    assert 0 < low < expected < high

    colors = color_info(result.grid.colors_used)
    text = inspection_text(result, settings, colors)
    for expected_line in (
        "toadstool.obj: ",
        "size in the file: ",
        "colours in the file: part/material colours on 100 % of the surface",
        "scale: ",
        "grid: ",
        "LEGO size: ",
        "hollow shell (wall 2): ",
        "LEGO colours: Red",
        "rough estimate: about ",
    ):
        assert expected_line in text
    picture = Image.open(io.BytesIO(render_inspection(result, colors, panel_px=300)))
    assert picture.size == (600, 300)


def test_uncoloured_open_mesh_and_solid_fill(fixtures_dir: Path) -> None:
    settings = load_settings(None, ["input.target_studs=12", "voxel.fill=solid"])
    result = inspect_file(fixtures_dir / "torus.stl", settings, name="torus")
    assert result.surface_colors == {}
    assert result.shell is result.grid
    text = inspection_text(result, settings, color_info(result.grid.colors_used))
    assert "none (the model gets color.single_color)" in text
    assert "hollow shell" not in text


def test_voxel_file(fixtures_dir: Path) -> None:
    settings = load_settings(None, [])
    result = inspect_file(fixtures_dir / "heart.vox", settings, name="heart")
    assert result.model is None
    colors = color_info(result.grid.colors_used)
    text = inspection_text(result, settings, colors)
    assert text.startswith("heart.vox: voxel grid, ")
    picture = Image.open(io.BytesIO(render_inspection(result, colors)))
    assert picture.size == (PANEL_PX, PANEL_PX)


def test_unsupported_file(tmp_path: Path) -> None:
    path = tmp_path / "model.dwg"
    path.write_text("x")
    with pytest.raises(ValueError, match=r"unsupported input format '\.dwg'"):
        inspect_file(path, load_settings(None, []), name="model")


def test_cli_inspect_writes_picture(fixtures_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "inspect",
            str(fixtures_dir / "bunny_lowpoly.stl"),
            "-o",
            str(tmp_path),
            "--set",
            "input.target_studs=12",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "rough estimate: about" in result.output
    assert (tmp_path / "bunny_lowpoly.inspect.png").is_file()


def test_cli_inspect_without_picture_and_errors(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "inspect",
            str(fixtures_dir / "heart.vox"),
            "-o",
            str(tmp_path),
            "--no-preview",
        ],
    )
    assert result.exit_code == 0, result.output
    assert not list(tmp_path.iterdir())
    tiny = runner.invoke(
        app,
        [
            "inspect",
            str(fixtures_dir / "sphere_r10.stl"),
            "-o",
            str(tmp_path),
            "--set",
            "input.scale_mode=mm",
            "--set",
            "input.mm_per_stud=500",
        ],
    )
    assert tiny.exit_code == 1
    assert "no voxels at this size" in tiny.output
    assert "--size 30cm" in tiny.output


def test_cli_inspect_shows_the_size_before_converting(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    """Roadmap 1: `inspect --size 30cm` shows the LEGO size it will get."""
    result = runner.invoke(
        app,
        [
            "inspect",
            str(fixtures_dir / "l_bracket.stl"),
            "-o",
            str(tmp_path),
            "--no-preview",
            "--size",
            "30cm",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "(height 30 cm -> 31 bricks)" in result.output
    assert "grid: 28 x 9 studs x 31 bricks" in result.output
    assert "LEGO size: 22.4 x 7.2 x 29.8 cm" in result.output


def test_cli_size_errors_name_the_problem(fixtures_dir: Path, tmp_path: Path) -> None:
    for command in ("inspect", "voxelize", "convert"):
        result = runner.invoke(
            app,
            [
                command,
                str(fixtures_dir / "l_bracket.stl"),
                "-o",
                str(tmp_path),
                "--size",
                "40",
            ],
        )
        assert result.exit_code == 1, command
        assert "give a number with a unit, e.g. 30cm" in result.output
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("shape", "parts"),
    [((2, 8, 1), 1), ((4, 8, 1), 2), ((1, 1, 3), 3), ((3, 3, 1), 2), ((2, 9, 2), 4)],
)
def test_quick_fill_uses_the_largest_bricks(
    shape: tuple[int, int, int], parts: int
) -> None:
    assert quick_fill(np.ones(shape, dtype=bool)) == parts


def test_estimate_falls_back_to_cells_for_huge_grids(
    fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = inspect_file(fixtures_dir / "heart.vox", load_settings(None, []), name="h")
    exact = result.parts_estimate
    monkeypatch.setattr("mesh2brick.inspection.MAX_FILL_CELLS", 0)
    rough = result.parts_estimate
    assert rough[1] == round(result.grid.filled_count / CELLS_PER_PART * 1.3)
    assert exact[0] <= 12 <= exact[2]  # heart.vox places 12 parts
