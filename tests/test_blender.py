# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""``.blend`` import through a headless Blender (Phase 8, ADR 0014).

Most tests use a stand-in "Blender" (a Python script with Blender's command
line) so the loader is tested everywhere. Tests marked ``blender`` run the
real Blender; they are skipped when it is missing, unless
``MESH2BRICK_REQUIRE_BLENDER=1``.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from mesh2brick.config import InputConfig
from mesh2brick.ingest import IngestError, load_model
from mesh2brick.ingest.blender import (
    BLENDER_ENV,
    BlenderLoader,
    blend_notes,
    blender_command,
    candidate_paths,
    find_blender,
    unit_scale,
)
from mesh2brick.ingest.blender_export import export_options, report, script_arguments

FAKE_BLENDER = """
import json, os, sys, time
import trimesh

args = sys.argv[1:]
glb, info = args[args.index("--") + 1:]
mode = os.environ.get("FAKE_BLENDER_MODE", "ok")
if mode == "fail":
    print("Error: File format is not supported in file 'x.blend'", file=sys.stderr)
    sys.exit(1)
if mode == "sleep":
    time.sleep(5)
box = trimesh.creation.box(extents=(20.0, 40.0, 10.0))  # Blender units, glTF y up
scene = trimesh.Scene()
scene.add_geometry(box, node_name="Tower", geom_name="Cube.001")
exported = ["Tower"]
if mode == "empty":
    exported = []
else:
    open(glb, "wb").write(scene.export(file_type="glb"))
data = {
    "blender": "4.0.1", "scene": "Scene", "unit_scale": 0.0010000000474974513,
    "length_unit": "MILLIMETERS", "exported": exported, "hidden": ["Helper"],
    "argv": args,
}
if mode != "noreport":
    open(info, "w").write(json.dumps(data))
"""


@pytest.fixture
def fake_blender(tmp_path: Path) -> Path:
    script = tmp_path / "fake_blender.py"
    script.write_text(FAKE_BLENDER, encoding="utf-8")
    launcher = tmp_path / "blender"
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return launcher


@pytest.fixture
def blend_file(tmp_path: Path) -> Path:
    path = tmp_path / "model.blend"
    path.write_bytes(b"BLENDER-v400")  # the stand-in never reads it
    return path


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="shell launcher")


@posix_only
def test_stand_in_blender_export_is_read_in_scene_units(
    fake_blender: Path, blend_file: Path
) -> None:
    raw = BlenderLoader(fake_blender).load(blend_file)
    assert raw.names == ("Tower",)
    # 1 Blender unit = 1 mm (unit scale 0.001); glTF's y up became z up.
    np.testing.assert_allclose(raw.parts[0].extents, [20, 10, 40], atol=1e-4)
    assert (
        raw.notes[0]
        == "read with Blender 4.0.1: 1 visible object(s), modifiers applied"
    )
    assert "skipped 1 hidden object(s): Helper" in raw.notes
    assert "Blender unit = 1 mm (scene unit scale 0.001, millimeters)" in raw.notes


@posix_only
def test_blender_runs_without_user_scripts(
    fake_blender: Path, blend_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []
    real_run = subprocess.run

    def spy(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(list(command))
        return real_run(command, **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(subprocess, "run", spy)
    BlenderLoader(fake_blender).load(blend_file)
    command = seen[0]
    for flag in ("--background", "--factory-startup", "--disable-autoexec"):
        assert flag in command
    # The file is opened before the export script runs.
    assert command.index(str(blend_file.resolve())) < command.index("--python")


@posix_only
@pytest.mark.parametrize(
    ("mode", "message"),
    [
        (
            "fail",
            r"Blender could not export model\.blend \(exit code 1\):\nError: File format",
        ),
        (
            "empty",
            r"model\.blend has no visible mesh, curve or text objects \(hidden: Helper\)",
        ),
        ("noreport", "Blender did not report what it exported"),
    ],
)
def test_blender_failures_are_explained(
    fake_blender: Path,
    blend_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    message: str,
) -> None:
    monkeypatch.setenv("FAKE_BLENDER_MODE", mode)
    with pytest.raises(IngestError, match=message):
        BlenderLoader(fake_blender).load(blend_file)


@posix_only
def test_blender_timeout(
    fake_blender: Path, blend_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BLENDER_MODE", "sleep")
    with pytest.raises(
        IngestError, match=r"did not finish exporting model\.blend within 1 s"
    ):
        BlenderLoader(fake_blender, timeout_s=1.0).load(blend_file)


def test_unstartable_blender(tmp_path: Path, blend_file: Path) -> None:
    not_executable = tmp_path / "blender.txt"
    not_executable.write_text("no program")
    with pytest.raises(IngestError, match="cannot start Blender"):
        BlenderLoader(not_executable).load(blend_file)


def test_missing_blender_explains_what_to_do(
    blend_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mesh2brick.ingest.blender.find_blender", lambda: None)
    with pytest.raises(IngestError, match=r"needs Blender .* MESH2BRICK_BLENDER"):
        load_model(blend_file, InputConfig())


def test_candidate_paths_per_platform(tmp_path: Path) -> None:
    env = {BLENDER_ENV: str(tmp_path / "my-blender"), "PATH": "", "HOME": str(tmp_path)}
    mac = candidate_paths(env, "darwin")
    assert mac[0] == tmp_path / "my-blender"
    assert Path("/Applications/Blender.app/Contents/MacOS/Blender") in mac
    assert tmp_path / "Applications/Blender.app/Contents/MacOS/Blender" in mac
    linux = candidate_paths({"PATH": "", "HOME": str(tmp_path)}, "linux")
    assert Path("/snap/bin/blender") in linux
    program_files = tmp_path / "Program Files"
    for version in ("4.0", "4.2"):
        exe = (
            program_files / "Blender Foundation" / f"Blender {version}" / "blender.exe"
        )
        exe.parent.mkdir(parents=True)
        exe.write_text("")
    windows = candidate_paths({"PATH": "", "ProgramFiles": str(program_files)}, "win32")
    assert [p.parent.name for p in windows] == ["Blender 4.2", "Blender 4.0"]


def test_find_blender_on_path_and_env(tmp_path: Path) -> None:
    exe = tmp_path / "blender"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    assert find_blender(env, "linux") == exe
    assert find_blender({"PATH": "", "HOME": str(tmp_path)}, "linux") is None
    with pytest.raises(IngestError, match="does not exist"):
        find_blender({BLENDER_ENV: str(tmp_path / "typo")}, "linux")


def test_export_script_helpers() -> None:
    options = export_options({"export_format", "export_colors", "use_visible"}, "x.glb")
    assert options == {
        "export_format": "GLB",
        "export_colors": True,
        "use_visible": True,
        "filepath": "x.glb",
    }
    assert script_arguments(["blender", "-b", "--", "a.glb", "a.json"]) == (
        Path("a.glb"),
        Path("a.json"),
    )
    for argv in (["blender"], ["blender", "--", "only-one"]):
        with pytest.raises(SystemExit, match="usage"):
            script_arguments(argv)
    data = report(
        version="4.0.1",
        scene="Scene",
        unit_scale=1.0,
        length_unit="METERS",
        exported=["b", "a"],
        hidden=[],
    )
    assert data["exported"] == ["a", "b"]


def test_notes_and_unit_scale() -> None:
    assert unit_scale({"unit_scale": 0.0010000000474974513}) == 0.001
    assert unit_scale({}) == 1.0
    assert unit_scale({"unit_scale": -2}) == 1.0
    notes = blend_notes(
        {
            "blender": "4.2.0",
            "exported": ["a"],
            "hidden": list("abcdefg"),
            "unit_scale": 1,
        }
    )
    assert notes == (
        "read with Blender 4.2.0: 1 visible object(s), modifiers applied",
        "skipped 7 hidden object(s): a, b, c, d, e, ...",
    )


def test_blender_command_order(tmp_path: Path) -> None:
    command = blender_command(
        Path("/b/blender"),
        tmp_path / "m.blend",
        tmp_path / "s.py",
        tmp_path / "o.glb",
        tmp_path / "o.json",
    )
    assert command[:5] == [
        "/b/blender",
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "-noaudio",
    ]
    assert command[-3:] == ["--", str(tmp_path / "o.glb"), str(tmp_path / "o.json")]


# ------------------------------------------------------------------ real Blender
def _real_blender() -> Path | None:
    try:
        return find_blender()
    except IngestError:
        return None


REAL_BLENDER = _real_blender()
needs_blender = pytest.mark.skipif(
    REAL_BLENDER is None and os.environ.get("MESH2BRICK_REQUIRE_BLENDER") != "1",
    reason="Blender is not installed (set MESH2BRICK_BLENDER)",
)


@needs_blender
@pytest.mark.blender
def test_real_blender_reads_the_rocket(fixtures_dir: Path) -> None:
    model = load_model(fixtures_dir / "rocket.blend", InputConfig())
    assert sorted(model.part_names) == ["Body", "Fins", "Nose", "Nozzle", "Window"]
    # Millimetre scene: 52 x 52 x 100 mm; the Array modifier made four fins.
    np.testing.assert_allclose(model.mesh.extents, [52, 52, 100], atol=0.01)
    assert model.watertight
    assert any(
        "skipped 1 hidden object(s): Helper (hidden)" in w for w in model.warnings
    )
    assert model.colors is not None
    colours = {tuple(int(v) for v in rgb) for rgb in model.colors.cad}
    assert len(colours) == 4  # white, red, blue, grey


VERTEX_PAINT = """
import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2)
attr = bpy.context.object.data.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
for d in attr.data:
    d.color_srgb = (1.0, 0.5, 0.0, 1.0)
bpy.ops.object.text_add(location=(4, 0, 0))
bpy.context.object.data.body = "A"
bpy.context.object.data.extrude = 0.2
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
"""


@needs_blender
@pytest.mark.blender
def test_real_blender_vertex_colours_and_text(tmp_path: Path) -> None:
    assert REAL_BLENDER is not None
    script = tmp_path / "make.py"
    script.write_text(VERTEX_PAINT)
    blend = tmp_path / "painted.blend"
    subprocess.run(
        [
            str(REAL_BLENDER),
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            str(blend),
        ],
        check=True,
        capture_output=True,
    )
    model = load_model(blend, InputConfig())
    assert set(model.part_names) == {"Cube", "Text"}
    assert model.colors is not None
    assert model.colors.vertex is not None
    painted = model.colors.vertex[model.colors.vertex_mask].reshape(-1, 3)
    assert (255, 128, 0) in {tuple(int(v) for v in rgb) for rgb in painted}


def test_report_is_json_serialisable() -> None:
    json.dumps(
        report(
            version="x",
            scene="s",
            unit_scale=1,
            length_unit="M",
            exported=[],
            hidden=[],
        )
    )
