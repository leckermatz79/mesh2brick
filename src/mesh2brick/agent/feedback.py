# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Local feedback store: runs, ratings, few-shot examples, fine-tuning export.

Every run with the LLM layer is recorded in a SQLite file on this computer
(nothing is uploaded): the model description Claude saw, what it proposed and
mesh2brick accepted, tokens and cost. ``mesh2brick feedback --rate 4 --note
"..."`` rates a run (by default the latest one).

Later runs learn from it in two ways: the accepted results of runs rated 4
or 5 become examples in the prompts (same task and language), and recent
notes are passed on as the builder's feedback. ``--export`` writes rated
runs as JSON lines for a later fine-tuning.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import platformdirs

if TYPE_CHECKING:
    from collections.abc import Iterator

GOOD_RATING: Final = 4
"""Runs rated at least this well provide examples for later prompts."""
FILE_NAME: Final = "feedback.sqlite3"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    created TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    language TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    parts INTEGER NOT NULL,
    steps INTEGER NOT NULL,
    cost_usd REAL,
    report TEXT NOT NULL,
    inputs TEXT NOT NULL,
    outputs TEXT NOT NULL,
    examples TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    created TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    note TEXT NOT NULL DEFAULT ''
);
"""


class FeedbackError(ValueError):
    """A rating or run reference is invalid."""


def default_store_path() -> Path:
    """Where the store lives (``MESH2BRICK_DATA_DIR`` overrides the folder)."""
    override = os.environ.get("MESH2BRICK_DATA_DIR")
    folder = (
        Path(override) if override else Path(platformdirs.user_data_dir("mesh2brick"))
    )
    return folder / FILE_NAME


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One run of the LLM layer, as stored.

    Attributes:
        name: model name.
        source: input file.
        language: booklet language.
        llm_model: Claude model id.
        parts, steps: size of the final model.
        cost_usd: cost of the run (``None``: unknown prices).
        report: the run report (tasks, tokens) as plain data.
        inputs: the model description Claude saw.
        outputs: what mesh2brick accepted, per task.
        examples: per task, example lines later prompts may show.
    """

    name: str
    source: str
    language: str
    llm_model: str
    parts: int
    steps: int
    cost_usd: float | None
    report: dict[str, Any] = field(default_factory=dict)
    inputs: str = ""
    outputs: dict[str, Any] = field(default_factory=dict)
    examples: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunSummary:
    """A stored run with its ratings, for listings."""

    id: int
    created: str
    name: str
    llm_model: str
    cost_usd: float | None
    ratings: tuple[int, ...]
    notes: tuple[str, ...]

    @property
    def rating(self) -> float | None:
        """Mean rating (``None``: not rated)."""
        return sum(self.ratings) / len(self.ratings) if self.ratings else None


class FeedbackStore:
    """The SQLite file of runs and ratings (created on first use)."""

    def __init__(self, path: Path) -> None:
        """Use the store at ``path``; nothing is touched until the first call."""
        self.path = path

    def _connect(self) -> closing[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA)
        return closing(connection)

    def record_run(self, record: RunRecord) -> int:
        """Store ``record`` and return its run id."""
        with self._connect() as db, db:
            cursor = db.execute(
                "INSERT INTO runs (created, name, source, language, llm_model, parts,"
                " steps, cost_usd, report, inputs, outputs, examples)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(),
                    record.name,
                    record.source,
                    record.language,
                    record.llm_model,
                    record.parts,
                    record.steps,
                    record.cost_usd,
                    json.dumps(record.report),
                    record.inputs,
                    json.dumps(record.outputs, ensure_ascii=False),
                    json.dumps(record.examples, ensure_ascii=False),
                ),
            )
            run_id = cursor.lastrowid
        if run_id is None:  # pragma: no cover - sqlite always sets it
            msg = "the run could not be stored"
            raise FeedbackError(msg)
        return run_id

    def rate(self, rating: int, note: str = "", run_id: int | None = None) -> int:
        """Rate a run (default: the latest) from 1 to 5; return its id.

        Raises:
            FeedbackError: for a rating outside 1-5 or an unknown run.
        """
        if not 1 <= rating <= 5:  # noqa: PLR2004 - the rating scale
            msg = f"ratings go from 1 to 5, got {rating}"
            raise FeedbackError(msg)
        with self._connect() as db, db:
            if run_id is None:
                row = db.execute("SELECT MAX(id) FROM runs").fetchone()
                run_id = row[0] if row else None
                if run_id is None:
                    msg = (
                        "no runs with the LLM layer yet (convert with llm.enabled=true)"
                    )
                    raise FeedbackError(msg)
            elif (
                db.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
                is None
            ):
                msg = f"there is no run {run_id}"
                raise FeedbackError(msg)
            db.execute(
                "INSERT INTO ratings (run_id, created, rating, note)"
                " VALUES (?, ?, ?, ?)",
                (run_id, _now(), rating, note.strip()),
            )
        return run_id

    def runs(self, limit: int = 20) -> list[RunSummary]:
        """The latest runs with their ratings, newest first."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, created, name, llm_model, cost_usd FROM runs"
                " ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            ratings: dict[int, list[tuple[int, str]]] = {}
            for run_id, rating, note in db.execute(
                "SELECT run_id, rating, note FROM ratings ORDER BY id"
            ):
                ratings.setdefault(run_id, []).append((rating, note))
        return [
            RunSummary(
                id=run_id,
                created=created,
                name=name,
                llm_model=llm_model,
                cost_usd=cost,
                ratings=tuple(r for r, _ in ratings.get(run_id, [])),
                notes=tuple(n for _, n in ratings.get(run_id, []) if n),
            )
            for run_id, created, name, llm_model, cost in rows
        ]

    def examples(self, task: str, language: str, limit: int) -> list[str]:
        """Example lines of ``task`` from well-rated runs, newest first."""
        if limit <= 0:
            return []
        lines: list[str] = []
        for examples in self._good_examples(language):
            lines.extend(json.loads(examples).get(task, []))
            if len(lines) >= limit:
                break
        return lines[:limit]

    def notes(self, limit: int) -> list[str]:
        """The latest non-empty rating notes, newest first."""
        if limit <= 0:
            return []
        with self._connect() as db:
            rows = db.execute(
                "SELECT rating, note FROM ratings WHERE note != '' ORDER BY id DESC"
                " LIMIT ?",
                (limit,),
            ).fetchall()
        return [f"{note} (rated {rating}/5)" for rating, note in rows]

    def export(self, path: Path) -> int:
        """Write every rated run as one JSON line per task; return the count."""
        count = 0
        with self._connect() as db:
            rows = db.execute(
                "SELECT r.id, r.language, r.llm_model, r.inputs, r.outputs,"
                " AVG(g.rating), GROUP_CONCAT(g.note, ' | ')"
                " FROM runs r JOIN ratings g ON g.run_id = r.id"
                " GROUP BY r.id ORDER BY r.id"
            ).fetchall()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as out:
            for run_id, language, llm_model, inputs, outputs, rating, notes in rows:
                for task, output in json.loads(outputs).items():
                    line = {
                        "run": run_id,
                        "task": task,
                        "language": language,
                        "llm_model": llm_model,
                        "input": inputs,
                        "output": output,
                        "rating": round(rating, 2),
                        "notes": notes.strip(" |") if notes else "",
                    }
                    out.write(json.dumps(line, ensure_ascii=False) + "\n")
                    count += 1
        return count

    def _good_examples(self, language: str) -> Iterator[str]:
        """The ``examples`` JSON of runs in ``language`` rated well, newest first."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT r.examples FROM runs r JOIN ratings g ON g.run_id = r.id"
                " WHERE r.language = ? GROUP BY r.id HAVING AVG(g.rating) >= ?"
                " ORDER BY r.id DESC",
                (language, GOOD_RATING),
            ).fetchall()
        for (value,) in rows:
            yield value


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
