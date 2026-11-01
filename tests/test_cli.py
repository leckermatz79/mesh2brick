# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mesh2brick import __version__
from mesh2brick.cli import EXIT_NOT_YET, app, model_name, progress_printer
from mesh2brick.model import BrickModel

runner = CliRunner()

COMMANDS = ("convert", "voxelize", "place", "render", "catalog", "inspect", "feedback")


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in COMMANDS:
        assert command in result.output


def test_help_runs_as_module() -> None:
    """Acceptance check for `mesh2brick --help` through the real interpreter."""
    result = subprocess.run(
        [sys.executable, "-m", "mesh2brick", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "place" in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["catalog"],
        ["inspect"],
        ["feedback"],
    ],
)
def test_planned_commands_say_so(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == EXIT_NOT_YET
    assert "planned for Phase" in result.output


def test_place_reports_config_errors(fixtures_dir: Path) -> None:
    result = runner.invoke(
        app, ["place", str(fixtures_dir / "heart.vox"), "--set", "voxel.fill=foam"]
    )
    assert result.exit_code == 1
    assert "voxel.fill" in result.output


def test_render_writes_png(tmp_path: Path, sample_model: BrickModel) -> None:
    model_path = sample_model.save(tmp_path / "tower.bricks.json")
    result = runner.invoke(app, ["render", str(model_path), "--step", "1"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "tower.png").stat().st_size > 1000


def test_render_rejects_bad_step(tmp_path: Path, sample_model: BrickModel) -> None:
    model_path = sample_model.save(tmp_path / "tower.bricks.json")
    result = runner.invoke(app, ["render", str(model_path), "--step", "9"])
    assert result.exit_code == 1
    assert "between 1 and 2" in result.output


def test_render_rejects_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.bricks.json"
    path.write_text("{}")
    result = runner.invoke(app, ["render", str(path)])
    assert result.exit_code == 1
    assert "cannot read brick model" in result.output


@pytest.mark.ldraw
def test_place_end_to_end(fixtures_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["place", str(fixtures_dir / "heart.vox"), "-o", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "buildable: yes" in result.output
    for name in ("heart.ldr", "heart.bricks.json", "heart.png"):
        assert (tmp_path / name).is_file(), name
    model = BrickModel.load(tmp_path / "heart.bricks.json")
    assert model.name == "heart"
    assert model.source.startswith("legolization")


@pytest.mark.ldraw
def test_place_mpd_output(fixtures_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "place",
            str(fixtures_dir / "heart.vox"),
            "-o",
            str(tmp_path),
            "--set",
            "output.formats=[mpd]",
            "--no-preview",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "heart.mpd").is_file()
    assert not (tmp_path / "heart.png").exists()


@pytest.mark.ldraw
def test_place_reports_backend_errors(fixtures_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "place",
            str(fixtures_dir / "heart.vox"),
            "-o",
            str(tmp_path),
            "--set",
            "placement.strategy=nope",
        ],
    )
    assert result.exit_code == 1
    assert "unknown placement strategy" in result.output


# ------------------------------------------------------------------ phase 1: voxelize
@pytest.mark.ldraw
def test_voxelize_writes_grid_preview_and_exports(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "voxelize",
            str(fixtures_dir / "l_bracket.stl"),
            "-o",
            str(tmp_path),
            "-s",
            "input.target_studs=10",
            "--vox",
            "--npy",
        ],
    )
    assert result.exit_code == 0, result.output
    for name in (
        "l_bracket.grid.npz",
        "l_bracket.voxels.png",
        "l_bracket.vox",
        "l_bracket.npy",
    ):
        assert (tmp_path / name).is_file(), name
    assert "volume method" in result.output
    assert "LEGO size" in result.output
    assert "hollow shell (wall 2)" in result.output


@pytest.mark.ldraw
def test_voxelize_then_place_npz(fixtures_dir: Path, tmp_path: Path) -> None:
    voxelized = runner.invoke(
        app,
        [
            "voxelize",
            str(fixtures_dir / "cube_10mm.stl"),
            "-o",
            str(tmp_path),
            "-s",
            "input.target_studs=4",
            "--no-preview",
        ],
    )
    assert voxelized.exit_code == 0, voxelized.output
    placed = runner.invoke(
        app, ["place", str(tmp_path / "cube_10mm.grid.npz"), "-o", str(tmp_path)]
    )
    assert placed.exit_code == 0, placed.output
    assert (tmp_path / "cube_10mm.ldr").is_file()
    assert BrickModel.load(tmp_path / "cube_10mm.bricks.json").name == "cube_10mm"


@pytest.mark.ldraw
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["-s", "color.single_color=9999"], "not solid colours"),
        (["-s", "color.mode=texture"], "arrives in Phase 3"),
    ],
)
def test_voxelize_reports_errors(
    fixtures_dir: Path, tmp_path: Path, args: list[str], message: str
) -> None:
    result = runner.invoke(
        app,
        ["voxelize", str(fixtures_dir / "cube_10mm.stl"), "-o", str(tmp_path), *args],
    )
    assert result.exit_code == 1
    assert message in result.output


@pytest.mark.ldraw
def test_voxelize_rejects_unsupported_files(tmp_path: Path) -> None:
    path = tmp_path / "model.step"
    path.write_text("ISO-10303-21;")
    result = runner.invoke(app, ["voxelize", str(path), "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "unsupported input format" in result.output


@pytest.mark.ldraw
def test_voxelize_warns_about_tiny_models(fixtures_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "voxelize",
            str(fixtures_dir / "cube_10mm.stl"),
            "-o",
            str(tmp_path),
            "-s",
            "input.scale_mode=mm",
            "-s",
            "input.mm_per_stud=40",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "no voxel reached the fill threshold" in result.output
    assert not (tmp_path / "cube_10mm.voxels.png").exists()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("duo.grid.npz", "duo"),
        ("duo.bricks.json", "duo"),
        ("duo.stl", "duo"),
        ("a.b.vox", "a.b"),
    ],
)
def test_model_name(name: str, expected: str) -> None:
    assert model_name(Path(name)) == expected


# ------------------------------------------------------------------ phase 2: convert
@pytest.mark.ldraw
def test_convert_end_to_end(fixtures_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "convert",
            str(fixtures_dir / "l_bracket.stl"),
            "-o",
            str(tmp_path),
            "-s",
            "input.target_studs=8",
        ],
    )
    assert result.exit_code == 0, result.output
    for suffix in (".ldr", ".bom.csv", ".bricklink.xml", ".rebrickable.csv", ".pdf"):
        assert (tmp_path / f"l_bracket{suffix}").is_file(), suffix
    assert "parts list total" in result.output
    assert "time:" in result.output


@pytest.mark.ldraw
def test_convert_reports_errors(tmp_path: Path) -> None:
    path = tmp_path / "model.step"
    path.write_text("ISO-10303-21;")
    result = runner.invoke(app, ["convert", str(path), "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "unsupported input format" in result.output


def test_progress_printer_thins_layer_lines(capsys: pytest.CaptureFixture[str]) -> None:
    show = progress_printer()
    for done in range(1, 41):
        show(f"layer {done}/40 ({done * 2}% of cells)")
    show("planning steps")
    lines = capsys.readouterr().out.splitlines()
    assert len([line for line in lines if "layer" in line]) == 5  # 0, 25, 50, 75, 100 %
    assert lines[-1] == "  planning steps"
