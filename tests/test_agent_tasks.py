# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""LLM tasks: what mesh2brick accepts from Claude, and what the tools say."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from tests.helpers import make_brick

from mesh2brick.agent import tasks
from mesh2brick.agent.describe import describe_model, kind_key, step_lines
from mesh2brick.agent.tools import MAX_PREVIEWS, ToolContext, tools_for
from mesh2brick.model import BrickModel, BuildStep, ColorInfo

COLOURS = {
    4: ColorInfo(name="Red", rgb_hex="#c91a09"),
    15: ColorInfo(name="White", rgb_hex="#ffffff"),
}


def row_model() -> BrickModel:
    """Six 2x4 bricks side by side, one per step; then two on top of the first."""
    parts = [make_brick("3001", 2 * i, 0, 0, i) for i in range(6)]
    parts += [
        replace(make_brick("3003", 0, 0, 3, 6, w=2, d=2), color=15),
        replace(make_brick("3003", 0, 2, 3, 6, w=2, d=2), color=15),
    ]
    return BrickModel(
        name="row",
        parts=tuple(parts),
        steps=(BuildStep(stable=True),) * 7,
        colors=COLOURS,
    )


def context(model: BrickModel | None = None, *, language: str = "de") -> ToolContext:
    return ToolContext(
        model=model or row_model(),
        language=language,  # type: ignore[arg-type]
        max_step_parts=3,
        render=lambda _model, step: f"png {step}".encode(),
    )


# ------------------------------------------------------------------ group_steps
def test_valid_merges_and_sections_are_kept() -> None:
    answer = {
        "merges": [{"first_step": 1, "last_step": 2, "reason": "pair"}],
        "sections": [
            {"first_step": 1, "title": "Sockel"},
            {"first_step": 7, "title": "Dach"},
        ],
    }
    grouping = tasks.read_grouping(context(), answer)
    assert grouping.merges == ((0, 1),)
    assert grouping.sections == {0: "Sockel", 6: "Dach"}
    assert grouping.rejected == ()
    assert tasks.check_grouping(context(), answer) == []


def test_bad_merges_are_dropped_with_reasons() -> None:
    answer = {
        "merges": [
            {"first_step": 1, "last_step": 4, "reason": "too big"},
            {"first_step": 3, "last_step": 4, "reason": "fine"},
            {"first_step": 4, "last_step": 5, "reason": "overlaps"},
            {"first_step": 6, "last_step": 7, "reason": "covers step 6? no"},
            {"first_step": "x", "last_step": 2, "reason": "garbage"},
        ],
        "sections": [],
    }
    grouping = tasks.read_grouping(context(), answer)
    assert grouping.merges == ((2, 3), (5, 6))
    text = " ".join(grouping.rejected)
    assert "4 parts (at most 3)" in text
    assert "overlaps" in text
    assert "integer" in text


def test_covered_parts_block_a_merge() -> None:
    answer = {"merges": [{"first_step": 1, "last_step": 7, "reason": ""}]}
    roomy = replace(context(), max_step_parts=20)
    (problem,) = tasks.read_grouping(roomy, answer).rejected
    assert "mostly covered" in problem


def test_section_rules() -> None:
    answer = {
        "merges": [{"first_step": 1, "last_step": 2, "reason": ""}],
        "sections": [
            {"first_step": 2, "title": "Inside a merge"},
            {"first_step": 3, "title": "Mitte"},
            {"first_step": 3, "title": "Again"},
            {"first_step": 4, "title": "mitte"},
            {"first_step": 5, "title": "x" * 30},
            {"first_step": 99, "title": "Nowhere"},
        ],
    }
    long = replace(row_model(), steps=(BuildStep(stable=True),) * 40)
    grouping = tasks.read_grouping(context(long), answer)
    assert grouping.sections == {2: "Mitte"}
    text = " ".join(grouping.rejected)
    for expected in (
        "inside a merged step",
        "increasing",
        "same title",
        "1-24 characters",
        "no such step",
        "first section must start at step 1",
    ):
        assert expected in text
    short = tasks.read_grouping(context(), answer)  # 7 steps: at most 2 sections
    assert "use at most 2 sections" in short.rejected


# ------------------------------------------------------------------ texts
def test_texts_must_fit_their_step() -> None:
    model = row_model()
    good = [{"part": "3003", "color": 15, "quantity": 2}]
    assert (
        tasks.text_problems(model, 6, "Setze 2 weiße Steine 2 × 2 oben auf.", good)
        == []
    )
    assert tasks.text_problems(model, 6, "Setze sie oben auf.", []) == []
    wrong_part = [{"part": "3001", "color": 4, "quantity": 1}]
    (problem,) = tasks.text_problems(model, 6, "Oben drauf.", wrong_part)
    assert "[3001/4] is not placed" in problem
    too_many = [{"part": "3003", "color": 15, "quantity": 3}]
    (problem,) = tasks.text_problems(model, 6, "Oben drauf.", too_many)
    assert "places 2, not 3" in problem
    (problem,) = tasks.text_problems(model, 6, "Setze 5 Steine oben auf.", [])
    assert "number(s) 5" in problem
    (problem,) = tasks.text_problems(model, 6, "x" * 141, [])
    assert "1-140 characters" in problem


def test_read_texts_keeps_the_good_ones() -> None:
    answer = {
        "texts": [
            {"step": 1, "text": "Lege den ersten Stein.", "mentions": []},
            {"step": 1, "text": "Doppelt.", "mentions": []},
            {"step": 2, "text": "Lege 7 Steine.", "mentions": []},
            {"step": 9, "text": "Weit weg.", "mentions": []},
        ]
    }
    texts, rejected = tasks.read_texts(row_model(), (0, 3), answer)
    assert texts == {0: "Lege den ersten Stein."}
    assert len(rejected) == 3
    missing = tasks.check_texts(context(), (0, 1), {"texts": answer["texts"][:1]})
    assert missing == ["texts missing for steps 2"]


def test_text_chunks_cover_every_step() -> None:
    model = row_model()
    big = replace(model, steps=(BuildStep(),) * 95)
    assert tasks.text_chunks(model) == [(0, 6)]
    assert tasks.text_chunks(big) == [(0, 39), (40, 79), (80, 94)]


# ------------------------------------------------------------------ choose_part
def test_choices_must_name_existing_options() -> None:
    questions = [
        tasks.PartQuestion("3008", 353, "1x Brick 1 x 8 in Coral", ("2x 1 x 4", "Red")),
        tasks.PartQuestion("3009", 353, "1x Brick 1 x 6 in Coral", ("3 + 3",)),
    ]
    answer = {
        "choices": [
            {"item": 1, "option": 2, "reason": "hidden"},
            {"item": 2, "option": 5, "reason": "?"},
            {"item": 3, "option": 1, "reason": "?"},
        ]
    }
    chosen, rejected = tasks.read_choices(questions, answer)
    assert chosen == {0: 1}
    assert len(rejected) == 2
    assert tasks.check_choices(questions, {"choices": []}) == [
        "no choice for item(s) 1-2"
    ]
    prompt = tasks.choices_prompt(questions, "de")[0]["text"]
    assert "Item 1: 1x Brick 1 x 8 in Coral" in prompt
    assert "Option 2: Red" in prompt


# ------------------------------------------------------------------ description
def test_description_names_parts_steps_and_support() -> None:
    model = row_model()
    text = describe_model(model, "de")
    assert '"row": 8 parts, 7 build steps' in text
    assert "[3001/4] Stein 2 × 4 Rot (en: Brick 2 x 4 Red): 6 in the model" in text
    lines = step_lines(model).splitlines()
    assert lines[0].startswith("Step 1 | main model | stands | layers 0-2")
    assert lines[0].endswith("| 1x [3001/4] | sits on the table")
    assert lines[6].endswith("2x [3003/15] | sits on step 1")
    assert kind_key(("3001", 4)) == "[3001/4]"


def test_sub_assembly_steps_do_not_sit_on_the_main_model() -> None:
    base = make_brick("3001", 0, 0, 0, 0)
    roof = make_brick("3001", 0, 0, 3, 1)
    model = BrickModel(
        name="house",
        parts=(base, roof),
        steps=(BuildStep(), BuildStep(submodel="roof"), BuildStep(attaches="roof")),
        colors=COLOURS,
    )
    lines = step_lines(model).splitlines()
    assert lines[1].endswith("first parts of the sub-assembly")
    assert lines[2].endswith("| sits on step 1")
    assert "attach sub-assembly A" in lines[2]


# ------------------------------------------------------------------ tools
def test_tools_check_merges_look_up_parts_and_draw_steps() -> None:
    ctx = context()
    tools = {tool.name: tool for tool in tools_for(ctx)}
    report = json.loads(
        tools["stability_check"].run(
            {
                "merges": [
                    {"first_step": 1, "last_step": 2},
                    {"first_step": 1, "last_step": 5},
                ]
            }
        )  # type: ignore[arg-type]
    )
    assert report[0] == {
        "steps": "1-2",
        "accepted": True,
        "after_merged_step": "stands on its own",
        "parts": 2,
    }
    assert report[1]["accepted"] is False
    rows = json.loads(tools["catalog_lookup"].run({"parts": ["3001", "nope"]}))  # type: ignore[arg-type]
    assert rows[0]["label"] == "Stein 2 × 4"
    assert rows[0]["in_model"] == 6
    assert "Red" in rows[0]["produced_in_model_colours"]
    assert rows[1] == {"part": "nope", "known": False}
    picture = tools["render_preview"].run({"step": 7})
    assert isinstance(picture, list)
    assert picture[0]["text"].startswith("Step 7: new parts")
    assert picture[1]["source"]["media_type"] == "image/png"
    with pytest.raises(ValueError, match="between 1 and 7"):
        tools["render_preview"].run({"step": 8})
    ctx.previews = MAX_PREVIEWS
    with pytest.raises(ValueError, match="limit"):
        tools["render_preview"].run({"step": 1})
    with pytest.raises(ValueError, match="at most"):
        tools["catalog_lookup"].run({"parts": ["3001"] * 41})


def test_tool_schemas_are_strict() -> None:
    for tool in tools_for(context()):
        definition = tool.definition()
        assert definition["strict"] is True
        assert definition["input_schema"]["additionalProperties"] is False
