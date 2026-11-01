# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""STEP import via cascadio (SPEC Phase 3)."""

from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mesh2brick.config import load_settings
from mesh2brick.ingest import IngestError, load_model
from mesh2brick.ingest.step import StepLoader, step_available
from mesh2brick.voxel.voxelize import voxelize

if os.environ.get("MESH2BRICK_REQUIRE_STEP"):
    import cascadio  # CI: a missing extra must fail, not skip
else:
    cascadio = pytest.importorskip("cascadio", reason="needs the optional 'step' extra")


def red_channel(rgb: np.ndarray) -> np.ndarray:
    return np.asarray(rgb, dtype=np.int32)[:, 0]


@pytest.mark.parametrize("studs", [8, 12, 32])
@pytest.mark.parametrize("height_unit", ["brick", "plate"])
def test_acceptance_step_and_stl_cube_give_identical_grids(
    fixtures_dir: Path, studs: int, height_unit: str
) -> None:
    settings = load_settings(
        None, [f"input.target_studs={studs}", f"voxel.height_unit={height_unit}"]
    )
    grids = [
        voxelize(load_model(fixtures_dir / name, settings.input), settings).grid
        for name in ("cube_10mm.step", "cube_10mm.stl")
    ]
    step, stl = grids
    assert step.shape == stl.shape
    np.testing.assert_array_equal(step.occupancy, stl.occupancy)
    np.testing.assert_array_equal(step.color, stl.color)
    np.testing.assert_allclose(step.origin_mm, stl.origin_mm, atol=1e-6)
    assert step.pitch_mm == pytest.approx(stl.pitch_mm)


def test_step_bodies_colours_and_units(fixtures_dir: Path) -> None:
    raw = StepLoader().load(fixtures_dir / "two_bodies.step")
    assert len(raw.parts) == 2  # two solids
    np.testing.assert_allclose(raw.parts[0].extents, (10, 10, 10), atol=1e-6)
    settings = load_settings(None, ["input.scale_mode=mm", "input.mm_per_stud=5"])
    model = load_model(fixtures_dir / "two_bodies.step", settings.input)
    assert model.watertight  # two closed solids that touch
    assert model.colors is not None
    grid = voxelize(model, settings, quantize=red_channel).grid
    # STEP 0.8 and 0.1 come back as sRGB ~204 and ~26. The detour through
    # linear glTF colours stored as bytes costs a few levels in dark tones.
    red, blue = (
        set(grid.color[:2].ravel().tolist()),
        set(grid.color[2:].ravel().tolist()),
    )
    assert len(red) == len(blue) == 1
    assert red.pop() == pytest.approx(204, abs=1)
    assert blue.pop() == pytest.approx(26, abs=3)


def test_multi_body_error(fixtures_dir: Path) -> None:
    settings = load_settings(None, ["input.multi_body=error"])
    with pytest.raises(IngestError, match="2 bodies"):
        load_model(fixtures_dir / "two_bodies.step", settings.input)
    load_model(fixtures_dir / "cube_10mm.step", settings.input)  # one body is fine


def test_tolerance_is_passed_in_millimetres(
    fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    original = cascadio.load

    def spy(data: bytes, **kwargs: Any) -> bytes:
        seen.update(kwargs)
        return bytes(original(data, **kwargs))

    monkeypatch.setattr(cascadio, "load", spy)
    settings = load_settings(None, ["input.step_tolerance_mm=0.2"])
    model = load_model(fixtures_dir / "cube_10mm.step", settings.input)
    assert seen["tol_linear"] == pytest.approx(0.2)
    assert seen["tol_relative"] is False
    assert any("0.2 mm tolerance" in note for note in model.warnings)


def test_unreadable_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = tmp_path / "broken.step"
    broken.write_text(
        "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    )
    with pytest.raises(IngestError, match="no shapes"):
        StepLoader().load(broken)
    monkeypatch.setattr(cascadio, "load", lambda *_a, **_k: b"")
    with pytest.raises(IngestError, match="no shapes"):
        StepLoader().load(broken)


def test_missing_extra_gives_install_hint(
    fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_import = builtins.__import__

    def no_cascadio(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "cascadio":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "cascadio")
    monkeypatch.setattr(builtins, "__import__", no_cascadio)
    assert not step_available()
    with pytest.raises(IngestError, match="uv sync --extra step"):
        StepLoader().load(fixtures_dir / "cube_10mm.step")


def test_step_available() -> None:
    assert step_available()
