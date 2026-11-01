# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mesh2brick import __version__
from mesh2brick.cli import EXIT_NOT_YET, app
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
        ["convert", "x.stl"],
        ["voxelize", "x.stl"],
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
