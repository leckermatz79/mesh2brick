# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The LLM tasks: prompts, answer schemas and the checks every answer passes.

* ``group_steps``: merge runs of consecutive steps a builder would do as one
  (checked by :func:`mesh2brick.steps.regroup.merge_problems`) and divide the
  steps into titled build sections.
* ``write_step_text``: one short sentence per step in the booklet language.
  Every part the text mentions as new must be placed in that step, and every
  number in it must be a quantity of that step.
* ``choose_part``: for parts LEGO does not make in their colour (only with
  ``parts.availability: report``), pick a replacement among options that
  mesh2brick computed from the catalogue.

Claude proposes, these checks decide: whatever fails is left out and the
deterministic result stays (ADR 0013).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from mesh2brick.agent import prompts
from mesh2brick.agent.client import image_block, text_block
from mesh2brick.agent.describe import kind_key
from mesh2brick.model import MAX_SECTION_CHARS
from mesh2brick.steps.regroup import merge_problems

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mesh2brick.agent.tools import ToolContext
    from mesh2brick.model import BrickModel
    from mesh2brick.render.text import Language

Range = tuple[int, int]
LANGUAGE_NAMES: Final = {"de": "German", "en": "English"}
MAX_TITLE_CHARS: Final = min(24, MAX_SECTION_CHARS)
MAX_TEXT_CHARS: Final = 140
TEXT_CHUNK: Final = 40
"""Steps per ``write_step_text`` conversation (bounds each answer's length)."""
_SIZES: Final = re.compile(
    r"\d+(?:[.,]\d+)?(?:\s*[" + chr(0xD7) + r"xX]\s*\d+(?:[.,]\d+)?)+"
)
"""Part sizes such as ``2 x 4`` (with the multiplication sign or an x)."""
_NUMBER: Final = re.compile(r"\d+")


def max_sections(model: BrickModel) -> int:
    """At most one section per four steps, at least two, at most twelve."""
    return max(2, min(12, model.step_count // 4))


# ------------------------------------------------------------------- schemas
def _object(**properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


INT: Final = {"type": "integer"}
STR: Final = {"type": "string"}
GROUPING_SCHEMA: Final = _object(
    merges=_array(_object(first_step=INT, last_step=INT, reason=STR)),
    sections=_array(_object(first_step=INT, title=STR)),
)
TEXTS_SCHEMA: Final = _object(
    texts=_array(
        _object(
            step=INT,
            text=STR,
            mentions=_array(_object(part=STR, color=INT, quantity=INT)),
        )
    )
)
CHOICES_SCHEMA: Final = _object(
    choices=_array(_object(item=INT, option=INT, reason=STR)),
)


def _with_extras(
    blocks: list[dict[str, Any]],
    heading: str,
    examples: Sequence[str],
    notes: Sequence[str],
) -> list[dict[str, Any]]:
    if examples:
        blocks.append(text_block(heading + "\n" + "\n".join(examples)))
    if notes:
        listed = "\n".join(f"- {note}" for note in notes)
        blocks.append(text_block(prompts.NOTES.format(notes=listed)))
    return blocks


# ------------------------------------------------------------------- group_steps
@dataclass(frozen=True, slots=True)
class Grouping:
    """What survives of a ``group_steps`` answer.

    Attributes:
        merges: runs of steps to merge (0-based, inclusive, ordered).
        sections: original 0-based step -> section title (always a step that
            starts a merged or unmerged step).
        rejected: why proposals were left out.
    """

    merges: tuple[Range, ...] = ()
    sections: dict[int, str] = field(default_factory=dict)
    rejected: tuple[str, ...] = ()


def grouping_prompt(
    context: ToolContext,
    picture: bytes,
    examples: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """First user message of ``group_steps``."""
    task = prompts.GROUPING.format(
        max_parts=context.max_step_parts,
        language=LANGUAGE_NAMES[context.language],
        max_title=MAX_TITLE_CHARS,
        max_sections=max_sections(context.model),
    )
    blocks = [text_block(task)]
    _with_extras(blocks, prompts.GROUPING_EXAMPLES, examples, notes)
    blocks.append(image_block(picture))
    return blocks


def check_grouping(context: ToolContext, answer: Any) -> list[str]:
    """Problems of a ``group_steps`` answer (empty: accept as a whole)."""
    return list(read_grouping(context, answer).rejected)


def read_grouping(context: ToolContext, answer: Any) -> Grouping:
    """The valid merges and sections of an answer, and what was rejected."""
    merges, rejected = _read_merges(context, _items(answer, "merges"))
    sections, more = _read_sections(context.model, merges, _items(answer, "sections"))
    return Grouping(merges=merges, sections=sections, rejected=(*rejected, *more))


def _read_merges(
    context: ToolContext, entries: list[dict[str, Any]]
) -> tuple[tuple[Range, ...], list[str]]:
    merges: list[Range] = []
    rejected: list[str] = []
    for merge in entries:
        first, last = merge.get("first_step"), merge.get("last_step")
        if not isinstance(first, int) or not isinstance(last, int):
            rejected.append(f"merge {merge!r} needs integer first_step and last_step")
            continue
        where = f"merge of steps {first}-{last}"
        if merges and first - 1 <= merges[-1][1]:
            rejected.append(f"{where} overlaps or comes before the previous merge")
            continue
        problems = merge_problems(
            context.model,
            context.structure,
            (first - 1, last - 1),
            max_size=context.max_step_parts,
        )
        if problems:
            rejected.append(f"{where}: {'; '.join(problems)}")
        else:
            merges.append((first - 1, last - 1))
    return tuple(merges), rejected


def _read_sections(
    model: BrickModel, merges: Sequence[Range], entries: list[dict[str, Any]]
) -> tuple[dict[int, str], list[str]]:
    inner = {step for first, last in merges for step in range(first + 1, last + 1)}
    rejected: list[str] = []
    if len(entries) > max_sections(model):
        rejected.append(f"use at most {max_sections(model)} sections")
        entries = entries[: max_sections(model)]
    sections: dict[int, str] = {}
    previous_step, previous_title = -1, ""
    for entry in entries:
        step, title = entry.get("first_step"), entry.get("title")
        if not isinstance(step, int) or not isinstance(title, str):
            rejected.append(f"section {entry!r} needs first_step and title")
            continue
        title = " ".join(title.split())
        problem = _section_problem(
            model,
            step - 1,
            title=title,
            inner=inner,
            previous_step=previous_step,
            previous_title=previous_title,
        )
        if problem:
            rejected.append(f"section {title!r} at step {step}: {problem}")
        else:
            sections[step - 1] = title
            previous_step, previous_title = step - 1, title
    if sections and min(sections) != 0:
        rejected.append("the first section must start at step 1")
    return sections, rejected


def _section_problem(
    model: BrickModel,
    step: int,
    *,
    title: str,
    inner: set[int],
    previous_step: int,
    previous_title: str,
) -> str | None:
    if not 0 <= step < model.step_count:
        return "no such step"
    if step in inner:
        return "the step is inside a merged step"
    if step <= previous_step:
        return "sections must start at increasing steps"
    if not 0 < len(title) <= MAX_TITLE_CHARS:
        return f"titles need 1-{MAX_TITLE_CHARS} characters"
    if title.casefold() == previous_title.casefold():
        return "same title as the section before"
    return None


def grouping_example(model: BrickModel) -> str:
    """How a rated run's sections appear among later runs' examples."""
    titles = ", ".join(
        f"{step.section} (step {i + 1})"
        for i, step in enumerate(model.steps)
        if step.section is not None
    )
    return (
        f'- "{model.name}" ({model.part_count} parts, {model.step_count} steps): '
        f"{titles}"
    )


# ------------------------------------------------------------------- write_step_text
def text_chunks(model: BrickModel) -> list[Range]:
    """0-based inclusive step ranges, one conversation each."""
    return [
        (start, min(start + TEXT_CHUNK, model.step_count) - 1)
        for start in range(0, model.step_count, TEXT_CHUNK)
    ]


def texts_prompt(
    context: ToolContext,
    chunk: Range,
    examples: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """First user message of ``write_step_text`` for one chunk of steps."""
    task = prompts.TEXTS.format(
        first=chunk[0] + 1,
        last=chunk[1] + 1,
        language=LANGUAGE_NAMES[context.language],
        max_chars=MAX_TEXT_CHARS,
    )
    return _with_extras([text_block(task)], prompts.TEXTS_EXAMPLES, examples, notes)


def check_texts(context: ToolContext, chunk: Range, answer: Any) -> list[str]:
    """Problems of a ``write_step_text`` answer (empty: accept as a whole)."""
    texts, rejected = read_texts(context.model, chunk, answer)
    missing = [step + 1 for step in range(chunk[0], chunk[1] + 1) if step not in texts]
    if missing and not rejected:
        rejected = [f"texts missing for steps {_ranges_text(missing)}"]
    return rejected


def read_texts(
    model: BrickModel, chunk: Range, answer: Any
) -> tuple[dict[int, str], list[str]]:
    """Valid texts (0-based step -> text) of an answer and why others failed."""
    texts: dict[int, str] = {}
    rejected: list[str] = []
    for entry in _items(answer, "texts"):
        step, text = entry.get("step"), entry.get("text")
        mentions = entry.get("mentions")
        if not isinstance(step, int) or not isinstance(text, str):
            rejected.append(f"entry {entry!r} needs step and text")
            continue
        if not chunk[0] + 1 <= step <= chunk[1] + 1:
            rejected.append(f"step {step} is outside {chunk[0] + 1}-{chunk[1] + 1}")
            continue
        if step - 1 in texts:
            rejected.append(f"step {step} has two texts")
            continue
        problems = text_problems(
            model, step - 1, text, mentions if isinstance(mentions, list) else []
        )
        if problems:
            rejected.append(f"step {step}: {'; '.join(problems)}")
        else:
            texts[step - 1] = " ".join(text.split())
    return texts, rejected


def text_problems(
    model: BrickModel, step: int, text: str, mentions: Sequence[Any]
) -> list[str]:
    """Why ``text`` does not fit the 0-based ``step`` (empty: it does)."""
    problems = []
    flat = " ".join(text.split())
    if not 0 < len(flat) <= MAX_TEXT_CHARS:
        problems.append(
            f"the text needs 1-{MAX_TEXT_CHARS} characters, has {len(flat)}"
        )
    counts = Counter((p.part, p.color) for p in model.parts_in_step(step))
    for mention in mentions:
        if not isinstance(mention, dict):
            problems.append(f"mention {mention!r} is not an object")
            continue
        part, colour = str(mention.get("part")), mention.get("color")
        quantity = mention.get("quantity")
        kind = (part, colour if isinstance(colour, int) else -1)
        if kind not in counts:
            problems.append(f"{kind_key(kind)} is not placed in this step")
        elif not isinstance(quantity, int) or not 0 <= quantity <= counts[kind]:
            problems.append(
                f"{kind_key(kind)}: the step places {counts[kind]}, not {quantity}"
            )
    allowed = {*counts.values(), sum(counts.values())}
    numbers = {int(n) for n in _NUMBER.findall(_SIZES.sub(" ", flat))}
    if stray := sorted(numbers - allowed):
        quantities = ", ".join(str(n) for n in sorted(allowed)) or "nothing"
        problems.append(
            f"the number(s) {', '.join(map(str, stray))} are not quantities of "
            f"this step (it places {quantities}); write part sizes like 2 x 4"
        )
    return problems


def text_example(model: BrickModel, step: int) -> str:
    """How a rated run's step text appears among later runs' examples."""
    counts = Counter((p.part, p.color) for p in model.parts_in_step(step))
    contents = ", ".join(f"{n}x {kind_key(k)}" for k, n in sorted(counts.items()))
    return f"- ({contents or 'attach step'}) {model.steps[step].text}"


# ------------------------------------------------------------------- choose_part
@dataclass(frozen=True, slots=True)
class PartQuestion:
    """A part LEGO does not make in its colour, and what could replace it.

    Attributes:
        part: LDraw part number.
        color: LDraw colour code the model uses.
        label: e.g. ``2x Brick 1 x 8 in Coral``.
        options: replacements, each checked against the catalogue; the first
            is mesh2brick's own choice.
    """

    part: str
    color: int
    label: str
    options: tuple[str, ...]


def choices_prompt(
    questions: Sequence[PartQuestion], language: Language
) -> list[dict[str, Any]]:
    """First user message of ``choose_part``."""
    items = "\n".join(
        f"Item {i + 1}: {q.label}\n"
        + "\n".join(f"  Option {j + 1}: {option}" for j, option in enumerate(q.options))
        for i, q in enumerate(questions)
    )
    task = prompts.CHOICES.format(language=LANGUAGE_NAMES[language], items=items)
    return [text_block(task)]


def check_choices(questions: Sequence[PartQuestion], answer: Any) -> list[str]:
    """Problems of a ``choose_part`` answer (empty: accept as a whole)."""
    return read_choices(questions, answer)[1]


def read_choices(
    questions: Sequence[PartQuestion], answer: Any
) -> tuple[dict[int, int], list[str]]:
    """Valid choices (item -> option, 0-based) and why others failed."""
    chosen: dict[int, int] = {}
    rejected: list[str] = []
    for entry in _items(answer, "choices"):
        item, option = entry.get("item"), entry.get("option")
        if not isinstance(item, int) or not 1 <= item <= len(questions):
            rejected.append(f"there is no item {item!r}")
        elif not isinstance(option, int) or not 1 <= option <= len(
            questions[item - 1].options
        ):
            rejected.append(f"item {item} has no option {option!r}")
        elif item - 1 in chosen:
            rejected.append(f"item {item} was answered twice")
        else:
            chosen[item - 1] = option - 1
    missing = [i + 1 for i in range(len(questions)) if i not in chosen]
    if missing and not rejected:
        rejected.append(f"no choice for item(s) {_ranges_text(missing)}")
    return chosen, rejected


# ------------------------------------------------------------------- helpers
def _items(answer: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(answer, dict):
        return []
    items = answer.get(key)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _ranges_text(numbers: Sequence[int]) -> str:
    """``[1, 2, 3, 7]`` -> ``1-3, 7``."""
    parts: list[str] = []
    start = previous = numbers[0]
    for value in [*numbers[1:], None]:
        if value is not None and value == previous + 1:
            previous = value
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        if value is not None:
            start = previous = value
    return ", ".join(parts)
