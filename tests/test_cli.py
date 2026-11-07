# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mesh2brick import __version__
from mesh2brick.cli import app, model_name, progress_printer
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
    for name in ("heart.mpd", "heart.bricks.json", "heart.png"):
        assert (tmp_path / name).is_file(), name
    model = BrickModel.load(tmp_path / "heart.bricks.json")
    assert model.name == "heart"
    assert model.source.startswith("legolization")


@pytest.mark.ldraw
def test_place_ldr_output(fixtures_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "place",
            str(fixtures_dir / "heart.vox"),
            "-o",
            str(tmp_path),
            "--set",
            "output.formats=[ldr]",
            "--no-preview",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "heart.ldr").is_file()
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
    assert (tmp_path / "cube_10mm.mpd").is_file()
    assert BrickModel.load(tmp_path / "cube_10mm.bricks.json").name == "cube_10mm"


@pytest.mark.ldraw
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["-s", "color.single_color=9999"], "not solid colours"),
        (["-s", "color.mode=rainbow"], "color.mode"),
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
    path = tmp_path / "model.fbx"
    path.write_text("Kaydara FBX Binary")
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
    for suffix in (".mpd", ".bom.csv", ".bricklink.xml", ".rebrickable.csv", ".pdf"):
        assert (tmp_path / f"l_bracket{suffix}").is_file(), suffix
    assert "parts list total" in result.output
    assert "time:" in result.output


@pytest.mark.ldraw
def test_convert_reports_errors(tmp_path: Path) -> None:
    path = tmp_path / "model.fbx"
    path.write_text("Kaydara FBX Binary")
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


# ------------------------------------------------------------------ catalog
@pytest.mark.ldraw
def test_acceptance_catalog_list_slopes_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC Phase 4: `catalog list --category slope` works offline."""

    def no_network(*_args: object, **_kwargs: object) -> None:
        msg = "network access during catalog list"
        raise AssertionError(msg)

    monkeypatch.setattr("socket.socket.connect", no_network)
    result = runner.invoke(app, ["catalog", "list", "--category", "slope"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split()[:3] == ["PART", "NAME", "SIZE"]
    parts = {line.split()[0] for line in lines[1:4]}
    assert parts == {"3039", "3040b", "4286"}
    assert "Brick Sloped 45° 2 x 2" in result.output  # Rebrickable name
    assert "3 part(s), 3 placeable" in result.output


@pytest.mark.ldraw
def test_catalog_list_shows_settings_and_json() -> None:
    result = runner.invoke(
        app, ["catalog", "list", "--json", "-s", "parts.exclude=[3001]"]
    )
    assert result.exit_code == 0, result.output
    import json  # noqa: PLC0415

    rows = {row["part"]: row for row in json.loads(result.output)}
    assert rows["3001"]["enabled"] is False
    assert rows["3003"]["enabled"] is True
    assert rows["3039"]["enabled"] is False  # slopes are opt-in
    assert rows["3001"]["size"] == "2 x 4 x 1 brick"
    assert rows["3001"]["bricklink"] == "3001"
    assert 4 in rows["3001"]["colors"]  # Red
    broken = runner.invoke(app, ["catalog", "list", "-s", "parts.exclude=[3005]"])
    assert broken.exit_code == 0
    assert "cannot remove 3005" in broken.output
    assert "?" in broken.output


@pytest.mark.ldraw
def test_catalog_list_all_and_errors() -> None:
    result = runner.invoke(app, ["catalog", "list", "--category", "tile", "--all"])
    assert result.exit_code == 0, result.output
    assert "not placeable" not in result.output
    assert int(result.output.split(" part(s)")[0].split()[-1]) > 4
    bad = runner.invoke(app, ["catalog", "list", "--category", "wheel"])
    assert bad.exit_code == 1
    assert "unknown category" in bad.output


@pytest.mark.ldraw
def test_catalog_show() -> None:
    result = runner.invoke(app, ["catalog", "show", "3001"])
    assert result.exit_code == 0, result.output
    assert "2 x 4 x 1 brick, 8 stud(s) on top" in result.output
    assert 'Rebrickable: 3001 "Brick 2 x 4"' in result.output
    assert "Coral" in result.output
    other = runner.invoke(app, ["catalog", "show", "3062b"])
    assert other.exit_code == 0
    assert "placeable: no" in other.output
    assert "colours: unknown" in other.output
    missing = runner.invoke(app, ["catalog", "show", "nope"])
    assert missing.exit_code == 1
    assert "nope" in missing.output


def test_feedback_rates_lists_and_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mesh2brick.agent.feedback import (  # noqa: PLC0415
        FeedbackStore,
        RunRecord,
        default_store_path,
    )

    monkeypatch.setenv("MESH2BRICK_DATA_DIR", str(tmp_path))
    empty = runner.invoke(app, ["feedback"])
    assert empty.exit_code == 0
    assert "no runs yet" in empty.output
    assert runner.invoke(app, ["feedback", "--rate", "4"]).exit_code == 1
    store = FeedbackStore(default_store_path())
    store.record_run(
        RunRecord(
            name="bunny",
            source="bunny.stl",
            language="de",
            llm_model="claude-sonnet-5-5",
            parts=10,
            steps=3,
            cost_usd=0.0831,
            outputs={"write_step_text": {"1": "Los."}},
        )
    )
    rated = runner.invoke(app, ["feedback", "--rate", "4", "--note", "schön"])
    assert rated.exit_code == 0, rated.output
    assert "rated run 1: 4/5 (schön)" in rated.output
    listed = runner.invoke(app, ["feedback"])
    assert "bunny" in listed.output
    assert "$0.083" in listed.output
    assert "4.0  schön" in listed.output
    out = tmp_path / "runs.jsonl"
    exported = runner.invoke(app, ["feedback", "--export", str(out)])
    assert "wrote 1 line(s)" in exported.output
    assert runner.invoke(app, ["feedback", "--rate", "9"]).exit_code == 2
    assert runner.invoke(app, ["feedback", "--note", "x"]).exit_code == 1
    assert runner.invoke(app, ["feedback", "--rate", "3", "--run", "7"]).exit_code == 1
