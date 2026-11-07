# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""A whole LLM run: tasks in order, fallbacks, cost, report and feedback store.

The pipeline test is Phase 7's acceptance test: ``convert`` with the LLM
layer on and off both give valid outputs, and the cost of the run is logged.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from tests.helpers import make_brick
from tests.llm_fakes import ScriptedClaude, answer, tool_call

from mesh2brick.agent.client import LlmError
from mesh2brick.agent.feedback import FeedbackStore
from mesh2brick.agent.session import LlmSession
from mesh2brick.config import Settings, load_settings
from mesh2brick.model import BrickModel, BuildStep, ColorInfo

if TYPE_CHECKING:
    from pathlib import Path

    from mesh2brick.pipeline import ConvertResult

RANGE = re.compile(r"steps (\d+) to (\d+)")


def texts_for(params: dict[str, Any]) -> Any:
    """Answer a write_step_text request with a valid text for every step."""
    prompt = " ".join(
        block.get("text", "")
        for block in params["messages"][0]["content"]
        if isinstance(block, dict)
    )
    first, last = map(int, RANGE.search(prompt).groups())  # type: ignore[union-attr]
    return answer(
        {
            "texts": [
                {
                    "step": s,
                    "text": f"Baue Teil {chr(64 + s % 26 + 1)} an.",
                    "mentions": [],
                }
                for s in range(first, last + 1)
            ]
        }
    )


def grouping(merges: list[tuple[int, int]], sections: dict[int, str]) -> Any:
    return answer(
        {
            "merges": [
                {"first_step": a, "last_step": b, "reason": "pair"} for a, b in merges
            ],
            "sections": [{"first_step": s, "title": t} for s, t in sections.items()],
        }
    )


def row_model() -> BrickModel:
    parts = tuple(make_brick("3001", 2 * i, 0, 0, i) for i in range(4))
    return BrickModel(
        name="row",
        parts=parts,
        steps=(BuildStep(stable=True),) * 4,
        colors={4: ColorInfo(name="Red", rgb_hex="#c91a09")},
    )


def session(claude: ScriptedClaude, settings: Settings | None = None) -> LlmSession:
    return LlmSession(
        settings or load_settings(None, ["llm.enabled=true"]),
        row_model(),
        send=claude,
        render=lambda _model, _step: b"png",
        picture=lambda _model: b"png",
        source="row.stl",
        examples=lambda task: [f"- example for {task}"],
        notes=["kürzere Texte bitte (rated 3/5)"],
    )


def test_session_runs_both_tasks_and_records_the_run(tmp_path: Path) -> None:
    claude = ScriptedClaude(
        tool_call("stability_check", {"merges": [{"first_step": 1, "last_step": 2}]}),
        grouping([(1, 2)], {1: "Links", 3: "Rechts"}),
        texts_for,
    )
    run = session(claude)
    result = run.group_steps()
    assert result.merges == ((0, 1),)
    merged = replace(
        row_model(),
        parts=tuple(replace(p, step=max(0, p.step - 1)) for p in row_model().parts),
        steps=(BuildStep(stable=True),) * 3,
    )
    run.use(merged)
    texts = run.write_step_texts()
    assert sorted(texts) == [0, 1, 2]
    model = run.annotate(merged)
    assert [s.section for s in model.steps] == ["Links", "Rechts", None]
    assert all(s.text for s in model.steps)
    store = FeedbackStore(tmp_path / "f.sqlite3")
    report = run.finish(model, store)
    assert report.run_id == 1
    assert [t.status for t in report.tasks] == ["accepted", "accepted"]
    assert report.usage.requests == 3
    assert report.cost_usd == pytest.approx(3 * (100 * 2 + 20 * 10) / 1e6)
    assert report.outputs["group_steps"]["merges"] == [[1, 2]]
    assert "group_steps" in report.summary()
    prompts = claude.prompts()
    assert "example for group_steps" in prompts[0]
    assert "kürzere Texte bitte" in prompts[2]
    assert "[section: Links]\nStep 1 |" in prompts[2]  # texts know the sections
    assert "[section:" not in prompts[0]
    assert "# The model" in prompts[0]
    model_block = claude.requests[0]["messages"][0]["content"][0]
    assert model_block["cache_control"] == {"type": "ephemeral"}
    assert claude.requests[0]["system"] == claude.requests[2]["system"]
    assert claude.requests[0]["tools"] == claude.requests[2]["tools"]
    (stored,) = store.runs()
    assert stored.name == "row"


def test_rejected_proposals_leave_the_model_as_it_was() -> None:
    claude = ScriptedClaude(
        grouping([(1, 9)], {2: "Später"}),  # no step 9; no section at step 1
        grouping([(1, 9)], {2: "Später"}),
    )
    settings = load_settings(None, ["llm.enabled=true", "llm.tasks=[group_steps]"])
    run = session(claude, settings)
    result = run.group_steps()
    assert result.merges == ()
    report = run.finish(run.annotate(row_model()), None)
    (task,) = report.tasks
    assert task.status == "partial"  # the section survives, the merge does not
    assert run.write_step_texts() == {}  # not enabled
    assert report.run_id is None


def test_fatal_errors_skip_the_remaining_tasks() -> None:
    def broken(_params: dict[str, Any]) -> Any:
        msg = "the API key was rejected"
        raise LlmError(msg, fatal=True)

    run = session(ScriptedClaude(broken))
    assert run.group_steps().merges == ()
    assert run.write_step_texts() == {}
    report = run.finish(row_model(), None)
    assert [t.status for t in report.tasks] == ["fallback", "skipped"]
    assert "key was rejected" in report.tasks[1].detail


def test_cost_limit_skips_tasks() -> None:
    settings = load_settings(None, ["llm.enabled=true", "llm.max_cost_usd=0.000001"])
    claude = ScriptedClaude(grouping([], {1: "Alles"}))
    run = session(claude, settings)
    run.group_steps()
    assert run.write_step_texts() == {}
    statuses = [t.status for t in run.finish(row_model(), None).tasks]
    assert statuses == ["accepted", "skipped"]


def test_unknown_model_prices_are_reported() -> None:
    settings = load_settings(None, ["llm.enabled=true", "llm.model=claude-future-9"])
    run = session(ScriptedClaude(), settings)
    assert "cannot be enforced" in run.notes_for_user[0]


def test_settings_validate_llm_options() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        load_settings(None, ["llm.tasks=[group_steps,group_steps]"])
    with pytest.raises(ValueError, match="effort"):
        load_settings(None, ["llm.effort=extreme"])


# ------------------------------------------------------------------ pipeline (acceptance)
@pytest.mark.ldraw
@pytest.mark.slow
def test_convert_with_and_without_llm(tmp_path: Path, fixtures_dir: Path) -> None:
    from mesh2brick.pipeline import convert  # noqa: PLC0415

    def run(enabled: bool, claude: ScriptedClaude | None = None) -> ConvertResult:
        settings = load_settings(
            None,
            [
                f"output.dir={tmp_path / ('on' if enabled else 'off')}",
                f"llm.enabled={str(enabled).lower()}",
                "llm.feedback=false",
            ],
        )
        return convert(fixtures_dir / "heart.vox", settings, name="heart", send=claude)

    plain = run(enabled=False)
    assert plain.llm is None
    assert not (tmp_path / "off" / "heart.llm.json").exists()

    # heart's steps are stacked: no merge would pass (see the tests above)
    claude = ScriptedClaude(grouping([], {1: "Unten", 6: "Oben"}), texts_for)
    improved = run(enabled=True, claude=claude)
    report = improved.llm
    assert report is not None
    assert [t.status for t in report.tasks] == ["accepted", "accepted"]
    assert report.cost_usd is not None
    assert report.cost_usd > 0
    model = improved.model
    assert model.step_count == plain.model.step_count
    assert [s.section for s in model.steps][::5] == ["Unten", "Oben"]
    assert all(step.text for step in model.steps)
    assert model.part_count == plain.model.part_count
    logged = json.loads((tmp_path / "on" / "heart.llm.json").read_text())
    assert logged["cost_usd"] == pytest.approx(report.cost_usd, abs=1e-4)
    assert logged["usage"]["requests"] == 2
    plain_mpd = (tmp_path / "off" / "heart.mpd").read_text()
    assert (tmp_path / "on" / "heart.mpd").read_text() == plain_mpd
    saved = BrickModel.load(tmp_path / "on" / "heart.bricks.json")
    assert saved.steps[0].section == "Unten"
    assert (tmp_path / "on" / "heart.pdf").stat().st_size > 0
    assert improved.bom.total == model.part_count


def test_improve_with_llm_merges_through_the_backend() -> None:
    from pathlib import Path  # noqa: PLC0415

    from mesh2brick.backends.protocols import Placement, StabilityReport  # noqa: PLC0415
    from mesh2brick.pipeline import improve_with_llm  # noqa: PLC0415

    merged_model = replace(
        row_model(),
        parts=tuple(replace(p, step=max(0, p.step - 1)) for p in row_model().parts),
        steps=(BuildStep(stable=True),) * 3,
    )

    class FakeBackend:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def merge_steps(self, placement: Placement, ranges: object) -> Placement:
            self.calls.append(ranges)
            return replace(placement, model=merged_model)

    placement = Placement(
        model=row_model(),
        stability=StabilityReport(
            stable=True, component_count=1, floating_count=0, max_score=0.0
        ),
        backend="fake",
    )
    backend = FakeBackend()
    settings = load_settings(None, ["llm.enabled=true", "llm.feedback=false"])
    claude = ScriptedClaude(grouping([(1, 2)], {1: "Alles"}), texts_for)
    said: list[str] = []
    outcome = improve_with_llm(
        placement,
        backend,  # type: ignore[arg-type]
        settings,
        source=Path("row.stl"),
        say=said.append,
        send=claude,
    )
    assert backend.calls == [((0, 1),)]
    new = outcome.placement
    assert new.model.step_count == 3
    assert new.model.steps[0].section == "Alles"
    assert outcome.report is not None
    assert outcome.notes == ()
    assert outcome.replacements == {}
    assert any("step texts for 3 steps" in line for line in said)


@pytest.mark.ldraw
def test_choose_part_suggests_catalogue_checked_replacements(tmp_path: Path) -> None:
    from pathlib import Path  # noqa: PLC0415

    from mesh2brick.backends.legolization import (  # noqa: PLC0415
        produced_in,
        replacement_options,
    )
    from mesh2brick.backends.protocols import Placement, StabilityReport  # noqa: PLC0415
    from mesh2brick.catalog.rebrickable import common_colors  # noqa: PLC0415
    from mesh2brick.export.bom import build_bom  # noqa: PLC0415
    from mesh2brick.pipeline import (  # noqa: PLC0415
        improve_with_llm,
        part_questions,
        pdf_options,
    )
    from mesh2brick.render.pdf import write_instructions  # noqa: PLC0415

    coral = 353
    assert produced_in("3008", coral) is False  # LEGO makes no 1 x 8 brick in Coral
    long_brick = replace(
        make_brick("3008", 0, 0, 0, 0, w=1, d=8), color=coral, category="brick"
    )
    model = BrickModel(
        name="coral",
        parts=(long_brick,),
        steps=(BuildStep(stable=True),),
        colors={coral: ColorInfo(name="Coral", rgb_hex="#ff698f")},
    )
    options = replacement_options("3008", coral, common_colors())
    assert options[0] == (("3010", coral), ("3010", coral))  # two 1 x 4 bricks
    assert all(produced_in(p, c) for option in options for p, c in option)
    questions, _ = part_questions(model)
    (question,) = questions
    assert question.label == "1x Brick 1 x 8 Coral"
    assert question.options[0] == "2x Brick 1 x 4 Coral (same colour)"

    settings = load_settings(
        None,
        [
            "llm.enabled=true",
            "llm.tasks=[choose_part]",
            "llm.feedback=false",
            "parts.availability=report",
        ],
    )
    placement = Placement(
        model=model,
        stability=StabilityReport(
            stable=True, component_count=1, floating_count=0, max_score=0.0
        ),
        backend="none",
    )
    claude = ScriptedClaude(
        answer({"choices": [{"item": 1, "option": 1, "reason": "Farbe bleibt"}]})
    )
    outcome = improve_with_llm(
        placement,
        None,  # type: ignore[arg-type]
        settings,
        source=Path("coral.stl"),
        say=lambda _line: None,
        send=claude,
    )
    assert outcome.replacements == {("3008", coral): "2x Stein 1 × 4 Coral (Koralle)"}
    assert outcome.report is not None
    assert outcome.report.tasks[0].status == "accepted"
    options_pdf = replace(
        pdf_options(settings, "coral"), replacements=outcome.replacements
    )
    report = write_instructions(
        model, build_bom(model), tmp_path / "c.pdf", options_pdf
    )
    assert report.pages == 3
