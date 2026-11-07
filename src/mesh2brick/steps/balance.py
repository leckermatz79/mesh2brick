# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Even step sizes: merge steps that are too small, split those too large.

Backends cut steps per layer, so a layer with one or two parts becomes a
step of its own (the product owner's Studio check found a step with a single
1 x 1 plate), and moving hanging parts to their holder can overfill a step.

:func:`merge_small_steps` merges a step with fewer than ``min_size`` parts
into the step before or after it when

* both build the same thing (main model or the same subassembly) and
  neither seats a subassembly,
* together they stay within ``max_size`` parts, and
* every part of the earlier step stays at least half visible: parts of the
  later step may sit on it, but cover at most half of its stud columns.

The merged step keeps both original steps in ``origin``; a verdict on the
model after the merged step is the verdict after the later original step.

:func:`split_large_steps` cuts a step with more than ``max_size`` parts into
spatially coherent pieces of about ``target`` parts. It only cuts between
groups of parts that do not touch, so no piece rests on a later piece; that
holds for layer-order steps, which is where it is used (checked plans keep
their checked step boundaries).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mesh2brick.steps.plan import PlanStep
    from mesh2brick.steps.structure import Structure

MAX_HIDDEN_SHARE: Final = 0.5
"""Largest share of an earlier part's columns a merged later step may cover."""


def merge_small_steps(
    steps: Sequence[PlanStep],
    structure: Structure,
    *,
    min_size: int,
    max_size: int,
) -> tuple[PlanStep, ...]:
    """Merge steps with fewer than ``min_size`` parts into a neighbour.

    Raises:
        ValueError: if ``min_size`` exceeds ``max_size``.
    """
    if min_size > max_size:
        msg = f"min_size {min_size} exceeds max_size {max_size}"
        raise ValueError(msg)
    merged: list[PlanStep] = []
    for step in steps:
        if merged and _mergeable(merged[-1], step, structure, min_size, max_size):
            merged[-1] = _merge(merged[-1], step)
        else:
            merged.append(step)
    return tuple(merged)


def split_large_steps(
    steps: Sequence[PlanStep],
    structure: Structure,
    *,
    target: int,
    max_size: int,
) -> tuple[PlanStep, ...]:
    """Cut main-model steps with more than ``max_size`` parts into pieces.

    Raises:
        ValueError: if ``target`` exceeds ``max_size`` or is not positive.
    """
    if not 0 < target <= max_size:
        msg = f"need 0 < target <= max_size, got {target} and {max_size}"
        raise ValueError(msg)
    result: list[PlanStep] = []
    for step in steps:
        if len(step.parts) <= max_size or not step.on_main_model:
            result.append(step)
            continue
        result.extend(_split(step, structure, target))
    return tuple(result)


def _split(step: PlanStep, structure: Structure, target: int) -> list[PlanStep]:
    """Pieces of ``step``; parts that touch (or form a unit) stay together."""
    order = {part: i for i, part in enumerate(step.parts)}
    groups = [set(g) for g in structure.components(step.parts)]
    for unit in step.units:  # units are connected, but keep them whole anyway
        touched = [g for g in groups if g & set(unit)]
        if len(touched) > 1:
            joined = set().union(*touched)
            groups = [g for g in groups if g not in touched] + [joined]
    columns = [structure.columns(g) for g in groups]
    xs = [x for c in columns for x, _ in c]
    ys = [y for c in columns for _, y in c]
    axis = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else 1
    ranked = sorted(
        range(len(groups)),
        key=lambda i: (
            sum(column[axis] for column in columns[i]) / len(columns[i]),
            min(order[p] for p in groups[i]),
        ),
    )
    pieces = math.ceil(len(step.parts) / target)
    share = len(step.parts) / pieces
    chunks: list[list[int]] = [[]]
    for i in ranked:
        if chunks[-1] and len(chunks[-1]) + len(groups[i]) / 2 > share:
            chunks.append([])
        chunks[-1].extend(sorted(groups[i], key=order.__getitem__))
    return [
        replace(
            step,
            parts=tuple(chunk),
            units=tuple(u for u in step.units if set(u) <= set(chunk)),
        )
        for chunk in chunks
    ]


def _mergeable(
    first: PlanStep,
    second: PlanStep,
    structure: Structure,
    min_size: int,
    max_size: int,
) -> bool:
    if min(len(first.parts), len(second.parts)) >= min_size:
        return False
    if len(first.parts) + len(second.parts) > max_size:
        return False
    if first.attaches is not None or second.attaches is not None:
        return False
    if first.submodel != second.submodel:
        return False
    if not structure.share_columns(first.parts, second.parts):
        return True
    return all(
        structure.hidden_share(part, second.parts) <= MAX_HIDDEN_SHARE
        for part in first.parts
    )


def _merge(first: PlanStep, second: PlanStep) -> PlanStep:
    return replace(
        first,
        parts=first.parts + second.parts,
        origin=first.origin + second.origin,
        units=first.units + second.units,
    )
