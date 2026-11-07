# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The local feedback store: runs, ratings, examples, fine-tuning export."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mesh2brick.agent.feedback import (
    FeedbackError,
    FeedbackStore,
    RunRecord,
    default_store_path,
)

if TYPE_CHECKING:
    from pathlib import Path


def record(name: str, *, language: str = "de", text: str = "Lege los.") -> RunRecord:
    return RunRecord(
        name=name,
        source=f"{name}.stl",
        language=language,
        llm_model="claude-sonnet-5-5",
        parts=10,
        steps=3,
        cost_usd=0.05,
        report={"tasks": []},
        inputs=f"model {name}",
        outputs={"write_step_text": {"1": text}},
        examples={"write_step_text": [f"- ({name}) {text}"], "group_steps": [name]},
    )


def test_runs_are_recorded_and_rated(tmp_path: Path) -> None:
    store = FeedbackStore(tmp_path / "sub" / "f.sqlite3")
    first = store.record_run(record("bunny"))
    second = store.record_run(record("duck"))
    assert store.rate(4, "  gut  ") == second  # the latest by default
    assert store.rate(2, "Texte zu lang", run_id=first) == first
    runs = store.runs()
    assert [r.name for r in runs] == ["duck", "bunny"]
    assert runs[0].ratings == (4,)
    assert runs[0].notes == ("gut",)
    assert runs[1].rating == 2.0
    assert store.notes(5) == ["Texte zu lang (rated 2/5)", "gut (rated 4/5)"]
    assert store.notes(0) == []


def test_invalid_ratings_are_refused(tmp_path: Path) -> None:
    store = FeedbackStore(tmp_path / "f.sqlite3")
    with pytest.raises(FeedbackError, match="no runs"):
        store.rate(3)
    store.record_run(record("bunny"))
    with pytest.raises(FeedbackError, match="1 to 5"):
        store.rate(6)
    with pytest.raises(FeedbackError, match="no run 99"):
        store.rate(3, run_id=99)


def test_examples_come_from_well_rated_runs_in_the_same_language(
    tmp_path: Path,
) -> None:
    store = FeedbackStore(tmp_path / "f.sqlite3")
    good = store.record_run(record("good", text="Gut."))
    bad = store.record_run(record("bad", text="Schlecht."))
    english = store.record_run(record("english", language="en", text="Fine."))
    store.record_run(record("unrated"))
    store.rate(5, run_id=good)
    store.rate(2, run_id=bad)
    store.rate(5, run_id=english)
    assert store.examples("write_step_text", "de", 5) == ["- (good) Gut."]
    assert store.examples("group_steps", "en", 5) == ["english"]
    assert store.examples("write_step_text", "de", 0) == []


def test_export_writes_one_line_per_rated_run_and_task(tmp_path: Path) -> None:
    store = FeedbackStore(tmp_path / "f.sqlite3")
    run = store.record_run(record("bunny"))
    store.record_run(record("unrated"))
    store.rate(5, "super", run_id=run)
    store.rate(3, "ok", run_id=run)
    out = tmp_path / "export" / "runs.jsonl"
    assert store.export(out) == 1
    (line,) = [json.loads(text) for text in out.read_text().splitlines()]
    assert line["task"] == "write_step_text"
    assert line["input"] == "model bunny"
    assert line["output"] == {"1": "Lege los."}
    assert line["rating"] == 4.0
    assert line["notes"] == "super | ok"


def test_default_path_follows_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MESH2BRICK_DATA_DIR", str(tmp_path))
    assert default_store_path() == tmp_path / "feedback.sqlite3"
    monkeypatch.delenv("MESH2BRICK_DATA_DIR")
    assert default_store_path().name == "feedback.sqlite3"
