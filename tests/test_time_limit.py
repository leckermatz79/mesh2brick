# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Roadmap 2: a hard time limit for legolization's run (ADR 0015)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, cast

import pytest

from mesh2brick.backends import BackendError
from mesh2brick.backends import legolization as module
from mesh2brick.backends.legolization import (
    LegolizationBackend,
    RunOutcome,
    RunState,
    choose_state,
    drop_loose_parts,
    load_voxel_file,
    run_placement,
    to_lego_grid,
    whitelist,
)
from mesh2brick.config import Settings
from mesh2brick.voxel.grid import VoxelGrid

pytestmark = pytest.mark.ldraw


@pytest.fixture(scope="module")
def heart(fixtures_dir: Path) -> VoxelGrid:
    return load_voxel_file(fixtures_dir / "heart.vox")


def _run_args(grid: VoxelGrid) -> tuple[Any, Any, frozenset[str]]:
    settings = Settings()
    allowed = whitelist(settings)
    config = LegolizationBackend().pipeline_config(
        settings, height_unit=grid.height_unit, allowed=allowed
    )
    return to_lego_grid(grid), config, allowed.parts


def _bricks(state: RunState) -> set[tuple[object, ...]]:
    return {(b.part_key, b.x, b.y, b.layer, b.yaw) for b in state.layout}


# ------------------------------------------------------------ choosing a state
class _Layout(list[int]):
    """Stands in for a legolization layout: only ``len()`` is used."""


def _state(stage: str, parts: int, rank: int) -> RunState:
    layout = _Layout(range(parts))
    layout.rank = rank  # type: ignore[attr-defined]
    return RunState(stage, cast("Any", layout), None)


def _rank(state: RunState) -> int:
    return int(state.layout.rank)  # type: ignore[attr-defined]


def test_finished_run_keeps_its_result() -> None:
    placed, final = _state("placed", 30, 2), _state("finished", 20, 2)
    state, notes = choose_state(RunOutcome((placed,), final), _rank)
    assert state is final
    assert notes == []


def test_finished_run_falls_back_to_an_earlier_stable_state() -> None:
    placed, final = _state("placed", 30, 2), _state("finished", 20, 1)
    state, notes = choose_state(RunOutcome((placed,), final), _rank)
    assert state is placed
    assert "left the model unstable" in notes[0]
    assert "30 parts" in notes[0]


def test_stopped_run_uses_the_latest_best_state() -> None:
    states = (
        _state("unchecked", 40, 0),
        _state("placed", 40, 1),
        _state("restored", 35, 2),
        _state("unchecked", 30, 0),
    )
    state, notes = choose_state(RunOutcome(states, None), _rank)
    assert state is states[2]
    assert "best stable model" in notes[0]
    assert "refilling weak hollow parts (35 parts)" in notes[0]
    unstable = choose_state(RunOutcome(states[:2], None), _rank)
    assert unstable[0] is states[1]
    assert "best (not stable)" in unstable[1][0]
    only = choose_state(RunOutcome(states[:1], None), _rank)
    assert "only model" in only[1][0]


def test_stopped_run_without_any_state_is_reported() -> None:
    with pytest.raises(BackendError, match="before legolization placed a first"):
        choose_state(RunOutcome((), None), _rank)


# ------------------------------------------------------------ running
def test_in_process_run_reports_its_states(heart: VoxelGrid) -> None:
    outcome = run_placement(*_run_args(heart))
    stages = [state.stage for state in outcome.states]
    assert stages[:2] == ["unchecked", "placed"]
    assert "remerged" in stages
    assert outcome.final is not None
    assert all(s.layout is not outcome.final.layout for s in outcome.states)


def test_child_run_gives_the_same_result(heart: VoxelGrid) -> None:
    said: list[str] = []
    here = run_placement(*_run_args(heart))
    there = run_placement(
        *_run_args(heart),
        stop_at=lambda _parts: time.monotonic() + 120,
        progress=said.append,
    )
    assert there.final is not None
    assert here.final is not None
    assert _bricks(there.final) == _bricks(here.final)
    assert [s.stage for s in there.states] == [s.stage for s in here.states]
    assert any(message.startswith("layer ") for message in said)


def test_child_run_stops_at_the_limit(heart: VoxelGrid) -> None:
    started = time.monotonic()
    # Wait for the first state, then stop at once.
    outcome = run_placement(
        *_run_args(heart),
        stop_at=lambda parts: started + 120 if parts == 0 else started,
    )
    assert outcome.final is None
    assert [s.stage for s in outcome.states] == ["unchecked"]
    assert len(outcome.states[0].layout) > 0


def test_child_run_reports_rejected_input(heart: VoxelGrid) -> None:
    grid, config, parts = _run_args(heart)
    empty = grid.with_codes(grid.codes * 0 - 1)
    with pytest.raises(BackendError, match="rejected the input"):
        run_placement(empty, config, parts, stop_at=lambda _p: time.monotonic() + 60)


def test_place_marks_a_model_cut_short(
    heart: VoxelGrid, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep no time for the export once the first state is known: the run
    # is stopped right after placement, before its stability check.
    monkeypatch.setattr(module, "export_reserve_s", lambda parts: 1e6 if parts else 0)
    placement = LegolizationBackend().place(
        heart, Settings(), name="h", deadline=time.monotonic() + 120
    )
    model = placement.model
    assert model.best_so_far
    assert model.buildable is None
    assert not placement.stability.checked
    assert not placement.stability.buildable
    assert any("time limit reached" in note for note in placement.notes)
    assert model.part_count > 0


# ------------------------------------------------------------ loose parts
def test_a_few_loose_parts_are_removed_and_checked_again(heart: VoxelGrid) -> None:
    grid, config, parts = _run_args(heart)
    final = run_placement(grid, config, parts).final
    assert final is not None
    layout = final.layout.copy()
    top = max(b.layer for b in layout) + 6
    layout.add("brick_1x1", 0, 0, top, 0, 4)  # floats far above the heart
    seen: list[RunState] = []
    loose = RunState("finished", layout, final.stability)
    cleaned = drop_loose_parts(loose, config, seen.append)
    assert cleaned is not None
    assert cleaned.loose_removed == ("3005",)
    assert len(cleaned.layout) == len(final.layout)
    assert cleaned.stability is not None
    assert cleaned.stability.stable
    assert seen == [loose]
    assert len(layout) == len(final.layout) + 1  # the input stays as it was
    assert drop_loose_parts(final, config) is None  # nothing loose


def test_many_loose_parts_stay(heart: VoxelGrid) -> None:
    grid, config, parts = _run_args(heart)
    final = run_placement(grid, config, parts).final
    assert final is not None
    layout = final.layout.copy()
    top = max(b.layer for b in layout) + 6
    for x in range(0, 2 * (module.MAX_LOOSE_PARTS + 1), 2):
        layout.add("brick_1x1", x, 0, top, 0, 4)
    assert (
        drop_loose_parts(RunState("finished", layout, final.stability), config) is None
    )
