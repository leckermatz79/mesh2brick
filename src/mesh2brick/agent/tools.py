# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The tools Claude may call while it works on a model (SPEC Phase 7).

* ``catalog_lookup``: names, sizes and the colours LEGO makes a part in,
  from the bundled offline catalogue.
* ``stability_check``: whether runs of steps may be merged, with the same
  check that later decides (:func:`mesh2brick.steps.regroup.merge_problems`),
  and whether the model stands after the merged step.
* ``render_preview``: a picture of the model after a step, new parts in full
  colour and earlier parts faded, as in the booklet.

All tools are offered in every task, so the cached prompt prefix (tools and
system prompt) is shared by all requests of a run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from mesh2brick.agent.client import Tool, image_block, text_block
from mesh2brick.agent.describe import colour_word, kind_key
from mesh2brick.catalog.rebrickable import available_colors, part_name
from mesh2brick.render.text import part_label
from mesh2brick.steps.regroup import merge_problems
from mesh2brick.steps.structure import Structure

if TYPE_CHECKING:
    from collections.abc import Callable

    from mesh2brick.model import BrickModel
    from mesh2brick.render.text import Language

MAX_PREVIEWS: Final = 12
"""Pictures per run; each costs a few hundred input tokens."""
MAX_LOOKUPS: Final = 40


@dataclass(slots=True)
class ToolContext:
    """What the tools work on; the current model can change between tasks.

    Attributes:
        model: the model as it stands (merged steps after ``group_steps``).
        language: language of the instructions.
        max_step_parts: largest allowed merged step.
        render: PNG of ``model`` after a 0-based step.
        previews: pictures handed out so far (limited per run).
    """

    model: BrickModel
    language: Language
    max_step_parts: int
    render: Callable[[BrickModel, int], bytes]
    previews: int = 0
    _structure: Structure | None = field(default=None, repr=False)

    @property
    def structure(self) -> Structure:
        """Stud connections of the current model's parts (by part index)."""
        if self._structure is None:
            self._structure = structure_of(self.model)
        return self._structure

    def use(self, model: BrickModel) -> None:
        """Work on ``model`` from now on."""
        self.model = model
        self._structure = None


def structure_of(model: BrickModel) -> Structure:
    """Stud connections of ``model.parts``, keyed by part index."""
    return Structure.from_cells(
        {i: p.cells for i, p in enumerate(model.parts)},
        {i: p.category for i, p in enumerate(model.parts)},
    )


def tools_for(context: ToolContext) -> tuple[Tool, ...]:
    """The three tools, bound to ``context``."""
    return (
        Tool(
            name="catalog_lookup",
            description=(
                "Look up LEGO parts in mesh2brick's offline catalogue: name, size, "
                "family and which colours of this model LEGO produces the part in. "
                "Call it when you are unsure what a part number is or how to name it."
            ),
            input_schema=_object(
                parts={
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "LDraw part numbers, e.g. ['3001', '3020'].",
                }
            ),
            run=lambda data: _catalog_lookup(context, data["parts"]),
        ),
        Tool(
            name="stability_check",
            description=(
                "Check proposed merges of consecutive build steps before you answer. "
                "For each run it reports whether mesh2brick would accept the merge "
                "(and why not) and whether the model stands after the merged step. "
                "Call it with every merge you consider; rejected merges are dropped."
            ),
            input_schema=_object(
                merges={
                    "type": "array",
                    "items": _merge_schema(),
                    "description": "Runs of consecutive steps (1-based, inclusive).",
                }
            ),
            run=lambda data: _stability_check(context, data["merges"]),
        ),
        Tool(
            name="render_preview",
            description=(
                "Show a picture of the model as built after one step: the parts of "
                "that step in full colour, earlier parts faded, as in the booklet. "
                f"Call it to see what a step builds. At most {MAX_PREVIEWS} pictures "
                "per run."
            ),
            input_schema=_object(
                step={"type": "integer", "description": "Step number (1-based)."}
            ),
            run=lambda data: _render_preview(context, data["step"]),
        ),
    )


def _object(**properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _merge_schema() -> dict[str, Any]:
    return _object(
        first_step={"type": "integer"},
        last_step={"type": "integer"},
    )


def _catalog_lookup(context: ToolContext, parts: list[str]) -> str:
    if len(parts) > MAX_LOOKUPS:
        msg = f"look up at most {MAX_LOOKUPS} parts at once"
        raise ValueError(msg)
    model = context.model
    used = {p.color for p in model.parts}
    rows = []
    for part in parts:
        example = next((p for p in model.parts if p.part == part), None)
        name = part_name(part)
        if example is None and name is None:
            rows.append({"part": part, "known": False})
            continue
        row: dict[str, Any] = {"part": part, "known": True, "name": name}
        if example is not None:
            row["label"] = part_label(example, context.language, name)
            row["family"] = example.category
            row["in_model"] = sum(1 for p in model.parts if p.part == part)
        colours = available_colors(part)
        if colours is not None:
            row["produced_in_model_colours"] = sorted(
                colour_word(model, c, "en") for c in colours & used
            )
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False)


def _stability_check(context: ToolContext, merges: list[dict[str, int]]) -> str:
    model = context.model
    report = []
    for merge in merges:
        first, last = merge["first_step"], merge["last_step"]
        problems = merge_problems(
            model,
            context.structure,
            (first - 1, last - 1),
            max_size=context.max_step_parts,
        )
        entry: dict[str, Any] = {"steps": f"{first}-{last}", "accepted": not problems}
        if problems:
            entry["problems"] = list(problems)
        else:
            stable = model.steps[last - 1].stable
            entry["after_merged_step"] = {
                True: "stands on its own",
                False: "needs a supporting hand",
                None: "not checked (layer order)",
            }[stable]
            entry["parts"] = sum(
                len(model.parts_in_step(s)) for s in range(first - 1, last)
            )
        report.append(entry)
    return json.dumps(report)


def _render_preview(context: ToolContext, step: int) -> list[dict[str, Any]]:
    model = context.model
    if not 1 <= step <= model.step_count:
        msg = f"step must be between 1 and {model.step_count}"
        raise ValueError(msg)
    if context.previews >= MAX_PREVIEWS:
        msg = f"the limit of {MAX_PREVIEWS} pictures per run is reached"
        raise ValueError(msg)
    context.previews += 1
    parts = model.parts_in_step(step - 1)
    contents = ", ".join(sorted({kind_key((p.part, p.color)) for p in parts}))
    caption = f"Step {step}: new parts in full colour, earlier parts faded."
    if contents:
        caption += f" New: {contents}."
    return [text_block(caption), image_block(context.render(model, step - 1))]
