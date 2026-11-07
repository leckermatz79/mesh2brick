# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Prompt texts of the LLM layer, in one place so they are easy to review.

Placeholders in braces are filled by :mod:`mesh2brick.agent.tasks`. The
system prompt is the same for every request of a run (with the model
description appended), so it stays in the prompt cache.
"""

from __future__ import annotations

from typing import Final

SYSTEM: Final = """\
You help mesh2brick, an open-source program that turns 3D models into \
LEGO-compatible models with building instructions, make its instructions easier \
to follow. Builders are hobbyists, sometimes children with a parent, who follow \
the PDF booklet step by step: each step shows the new parts with their \
quantities and a picture of the model with the new parts in full colour.

mesh2brick has already placed every part and checked the model. You never change \
parts, colours, positions or the order in which parts are placed. mesh2brick \
checks everything you propose against the model and drops what does not pass, \
so a smaller answer that is correct beats a bigger one with mistakes.

How the model is described below: x runs from left to right and y from front to \
back, in studs; height is counted in plates from the bottom (a brick is 3 plates \
high). Parts in a colour have keys like [3001/4] (LDraw part number / LDraw \
colour code). Sub-assemblies are built separately on the table and attached to \
the main model in their own step."""

MODEL: Final = """\
# The model

{overview}

## Parts in colours

{kinds}

## Build steps

Step | where | after the step the model ... | position of new parts | new parts | \
what the new parts sit on

{steps}"""

GROUPING: Final = """\
Task: structure the build steps of this model. The picture shows the finished \
model.

1. Merges (optional). Propose runs of consecutive steps that a builder would \
rather do as one step: small steps that continue the same piece of work, a left \
and a right side built the same way, or steps that together finish one \
recognisable part. A merged step may have at most {max_parts} parts. Check your \
merges with stability_check before you answer; only merges it accepts count. \
Merging is never required: leave steps alone when in doubt, and do not merge \
just to have fewer steps.

2. Sections. Divide the steps into build sections with short titles in \
{language} (1 to 3 words, at most {max_title} characters), the way building \
instructions name stages, such as "Base", "Body", "Head", "Left wing" (in \
German "Sockel", "Körper", "Kopf", "Linker Flügel"). Name what the steps build, \
judged from the picture and from where the steps place their parts (layers and \
position). The first section starts at step 1; every section starts at a step \
that begins a merged or unmerged step. Use 2 to {max_sections} sections; a \
sub-assembly's steps form a section of their own, named after what it is \
("Lid", "Left ear"), not its letter: the booklet labels sub-assemblies itself. \
A title differs from the title before it.

Answer in the JSON format: "merges" (first_step, last_step, a short reason) and \
"sections" (first_step, title), with the step numbers of the step list."""

GROUPING_EXAMPLES: Final = "Sections of earlier models that the builder rated highly:"

TEXTS: Final = """\
Task: write a short instruction for each of the steps {first} to {last}, in \
{language}.

- One sentence of at most {max_chars} characters in plain words that a \
ten-year-old understands. The booklet already shows the picture of the step and \
every new part with its quantity, so do not list the parts again. Say what the \
step achieves and where the new parts go, using the part of the model they sit \
on: "Close the ring around the stem.", "Now the brim of the cap grows towards \
the back.", "Put the white dots on top of the cap." Name a part only when that \
helps to find its place ("the long red brick goes across the front").
- Address the builder directly and the same way in every step: an instruction \
("Put the cap on the stem.", German with "du": "Setze den Hut auf den Stiel.", \
"Jetzt baust du die Ohren."), never "we".
- Write every quantity as digits ("2 red bricks", "2 rote Steine"). Do not \
mention step numbers, part numbers, layers or coordinates; write part sizes as \
"2 × 4".
- The parts you mention as new must be parts of that step: list each in \
"mentions" with its key from the step list (part, color) and the quantity your \
text gives (0 if the text gives none). Parts that are already in the model may \
be named to say where the new parts go; do not list those.
- A sub-assembly step says what is being built; an attach step says where the \
sub-assembly goes. When the model needs a hand after a step, the booklet adds \
that hint itself.
- The section titles in the step list say what a group of steps builds; use \
them ("the ear grows taller", not "the tower grows").
- Vary the wording; use render_preview when a step is hard to picture.

Answer in the JSON format: "texts" with one entry (step, text, mentions) for \
every step from {first} to {last}."""

TEXTS_EXAMPLES: Final = "Step texts of earlier models that the builder rated highly:"

CHOICES: Final = """\
Task: LEGO does not produce the following parts in the colour the model uses. \
For each item, choose the replacement a builder should buy. Prefer keeping the \
colour (shorter parts of the same colour) where the part shows; a neighbouring \
colour is fine for hidden inner parts or when no same-colour option exists. Give \
a short reason in {language}.

{items}

Answer in the JSON format: "choices" with one entry (item, option, reason) per \
item."""

NOTES: Final = """\
Feedback the builder gave on earlier instructions (take it into account):
{notes}"""

FIX: Final = """\
mesh2brick checked your answer against the model and found these problems:
{problems}

Fix them and send the complete answer again in the same JSON format. Parts of \
the answer that still have problems will be left out."""
