# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The brick model in words, for prompts: overview, part kinds and steps.

Claude cannot read cells; it gets one line per build step instead: where the
step builds (main model or a sub-assembly), whether the model stands after
it, where in the model its parts sit, and which parts it places, each with
an ``[part/colour]`` key that answers refer back to.

Coordinates as the prompt explains them: ``x`` runs left to right and ``y``
front to back, in studs; height is counted in plates (a brick is 3 plates).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Final

from mesh2brick.agent import prompts
from mesh2brick.catalog.rebrickable import part_name
from mesh2brick.render.text import (
    german_colour_names,
    number,
    part_label,
    subassembly_label,
)
from mesh2brick.steps.structure import Structure

if TYPE_CHECKING:
    from mesh2brick.model import BrickModel, PlacedPart
    from mesh2brick.render.text import Language

THIRDS: Final = (1 / 3, 2 / 3)
Kind = tuple[str, int]


def kind_key(kind: Kind) -> str:
    """``[3001/4]``: how prompts and answers name a part in a colour."""
    return f"[{kind[0]}/{kind[1]}]"


def colour_word(model: BrickModel, code: int, language: Language) -> str:
    """Colour name for prose: German in German (``Rot``), else the catalogue name."""
    english = (
        model.colors[code].name.replace("_", " ") if code in model.colors else str(code)
    )
    if language == "de":
        return german_colour_names().get(code, english)
    return english


def kind_label(model: BrickModel, kind: Kind, language: Language) -> str:
    """``Platte 2 x 4 Rot`` / ``Plate 2 x 4 Red`` for a part in a colour."""
    example = next(p for p in model.parts if (p.part, p.color) == kind)
    name = part_label(example, language, part_name(kind[0]))
    return f"{name} {colour_word(model, kind[1], language)}"


def describe_model(model: BrickModel, language: Language) -> str:
    """The whole description: overview, part kinds and build steps."""
    return prompts.MODEL.format(
        overview=overview(model),
        kinds=part_kinds(model, language),
        steps=step_lines(model),
    )


def overview(model: BrickModel) -> str:
    """A few lines about the whole model (in English, for Claude)."""
    width, depth, height = (v / 10 for v in model.size_mm())
    counts = Counter(p.color for p in model.parts)
    colours = ", ".join(
        f"{colour_word(model, code, 'en')} ({count})"
        for code, count in counts.most_common()
    )
    (x0, y0, z0), (x1, y1, z1) = model.bounds()
    checked = all(step.stable is not None for step in model.steps)
    size = " x ".join(number(v, "en") for v in (width, depth, height))
    lines = [
        (
            f'Model "{model.name}": {model.part_count} parts, {model.step_count} '
            f"build steps, {size} cm (width x depth x height)."
        ),
        f"Colours (parts): {colours}.",
        f"Extent: x {x0}-{x1}, y {y0}-{y1} studs; height layers {z0}-{z1} (plates).",
        (
            "Every intermediate state was checked: 'stands' means the model holds "
            "on its own after the step, 'needs a hand' means the builder must hold it."
            if checked
            else "Steps follow the layers bottom-up; intermediate states were not "
            "checked for stability."
        ),
    ]
    if model.submodels:
        names = ", ".join(subassembly_label(i) for i in range(len(model.submodels)))
        lines.append(f"Sub-assemblies (built separately, then attached): {names}.")
    return "\n".join(lines)


def part_kinds(model: BrickModel, language: Language) -> str:
    """One line per part in a colour: key, name and how many the model uses."""
    counts = Counter((p.part, p.color) for p in model.parts)
    lines = []
    for kind in sorted(counts, key=lambda k: (-counts[k], k)):
        label = kind_label(model, kind, language)
        english = kind_label(model, kind, "en") if language != "en" else ""
        extra = f" (en: {english})" if english and english != label else ""
        lines.append(f"{kind_key(kind)} {label}{extra}: {counts[kind]} in the model")
    return "\n".join(lines)


def step_lines(model: BrickModel) -> str:
    """One line per build step (1-based numbers)."""
    labels = {name: subassembly_label(i) for i, name in enumerate(model.submodels)}
    structure = Structure.from_cells(
        {i: p.cells for i, p in enumerate(model.parts)},
        {i: p.category for i, p in enumerate(model.parts)},
    )
    (x0, y0, _), (x1, y1, _) = model.bounds()
    lines = []
    for index, step in enumerate(model.steps):
        parts = model.parts_in_step(index)
        if step.submodel is not None:
            where = f"sub-assembly {labels[step.submodel]}"
        elif step.attaches is not None:
            where = f"attach sub-assembly {labels[step.attaches]} to the main model"
        else:
            where = "main model"
        verdict = {True: "stands", False: "needs a hand", None: "not checked"}[
            step.stable
        ]
        text = f"Step {index + 1} | {where} | {verdict}"
        if parts:
            text += f" | {_position(parts, (x0, x1), (y0, y1))} | {_contents(parts)}"
        text += f" | {_support(model, structure, index, labels)}"
        if any(p.unit is not None for p in parts):
            text += " | some parts are put together in the hand first"
        lines.append(text)
    return "\n".join(lines)


def _support(
    model: BrickModel, structure: Structure, step: int, labels: dict[str, str]
) -> str:
    """What the new parts of ``step`` sit on (and hang from), by earlier step."""
    steps = model.steps
    current = steps[step]
    if current.attaches is not None:
        new = {
            i
            for i, p in enumerate(model.parts)
            if steps[p.step].submodel == current.attaches
        }
    else:
        new = {i for i, p in enumerate(model.parts) if p.step == step}
    if not new:
        return "places nothing"
    floor = min(z for p in model.parts for _, _, z in p.cells)
    context = current.submodel

    def name(part: int) -> str:
        owner = steps[model.parts[part].step].submodel
        if owner is not None and owner != context:
            return f"sub-assembly {labels[owner]}"
        return f"step {model.parts[part].step + 1}"

    def present(part: int) -> bool:
        """Whether ``part`` is in place while ``step`` is built.

        Sub-assemblies are built on their own, without the main model.
        """
        owner = steps[model.parts[part].step].submodel
        return part not in new and (context is None or owner == context)

    below = {name(j) for i in new for j in structure.below[i] if present(j)}
    above = {
        name(j)
        for i in new
        for j in structure.above[i]
        if present(j) and model.parts[j].step < step
    }
    on_table = context is None and any(
        min(z for _, _, z in model.parts[i].cells) == floor for i in new
    )
    words = []
    if below or on_table:
        listed = sorted(below, key=_natural) + (["the table"] if on_table else [])
        words.append("sits on " + ", ".join(listed))
    if above:
        words.append("is held from above by " + ", ".join(sorted(above, key=_natural)))
    return "; ".join(words) or "first parts of the sub-assembly"


def _natural(label: str) -> tuple[str, int]:
    """Sort ``step 9`` before ``step 10``."""
    word, _, number_text = label.rpartition(" ")
    return (word, int(number_text)) if number_text.isdigit() else (label, 0)


def _contents(parts: tuple[PlacedPart, ...]) -> str:
    counts = Counter((p.part, p.color) for p in parts)
    return ", ".join(
        f"{counts[kind]}x {kind_key(kind)}"
        for kind in sorted(counts, key=lambda k: (-counts[k], k))
    )


def _position(
    parts: tuple[PlacedPart, ...], xs: tuple[int, int], ys: tuple[int, int]
) -> str:
    cells = [cell for p in parts for cell in p.cells]
    px = [c[0] for c in cells]
    py = [c[1] for c in cells]
    pz = [c[2] for c in cells]
    words = (
        _third(sum(px) / len(px), xs, ("left", "centre", "right")),
        _third(sum(py) / len(py), ys, ("front", "middle", "back")),
    )
    return (
        f"layers {min(pz)}-{max(pz)}, x {min(px)}-{max(px)}, y {min(py)}-{max(py)} "
        f"({words[0]} {words[1]})"
    )


def _third(value: float, span: tuple[int, int], names: tuple[str, str, str]) -> str:
    low, high = span
    share = 0.5 if high == low else (value - low) / (high - low)
    if share < THIRDS[0]:
        return names[0]
    return names[1] if share <= THIRDS[1] else names[2]
