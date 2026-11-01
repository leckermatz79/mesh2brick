# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Split a brick into shorter ones: the arithmetic behind colour substitution.

A placed brick that LEGO does not make in its colour (e.g. a 1 x 8 brick in
Bright Green) is replaced by shorter bricks of the same width, height and
colour that do exist. :func:`choose_split` picks the pieces: as few as
possible, and with the joints away from joints in the layers directly above
and below, because joints on top of each other weaken a wall (running bond).
"""

from __future__ import annotations

from functools import cache
from itertools import permutations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable


def split_options(length: int, lengths: Iterable[int]) -> list[tuple[int, ...]]:
    """Every ordering of the minimal-count partitions of ``length``.

    ``lengths`` are the available piece lengths (studs). Returns ``[]`` if
    ``length`` cannot be covered exactly.
    """
    usable = tuple(sorted({k for k in lengths if 0 < k <= length}, reverse=True))
    if length <= 0 or not usable:
        return []

    @cache
    def fewest(rest: int) -> int | None:
        if rest == 0:
            return 0
        counts = [c for k in usable if k <= rest if (c := fewest(rest - k)) is not None]
        return min(counts) + 1 if counts else None

    best = fewest(length)
    if best is None:
        return []
    multisets: set[tuple[int, ...]] = set()

    def collect(rest: int, chosen: tuple[int, ...]) -> None:
        if rest == 0:
            multisets.add(tuple(sorted(chosen, reverse=True)))
            return
        for k in usable:
            if k <= rest and fewest(rest - k) == best - len(chosen) - 1:
                collect(rest - k, (*chosen, k))

    collect(length, ())
    return sorted({order for parts in multisets for order in permutations(parts)})


def joints(pieces: tuple[int, ...]) -> tuple[int, ...]:
    """Offsets of the internal joints of a split (``(4, 4)`` -> ``(4,)``)."""
    offsets, position = [], 0
    for piece in pieces[:-1]:
        position += piece
        offsets.append(position)
    return tuple(offsets)


def choose_split(
    length: int, lengths: Iterable[int], avoid: Collection[int] = ()
) -> tuple[int, ...] | None:
    """Best split of ``length`` into available ``lengths`` (``None``: impossible).

    Fewest pieces first; then fewest joints at ``avoid`` (joints of the
    neighbouring layers); then joints closest to the middle (balanced
    pieces); ties resolved deterministically.
    """
    options = split_options(length, lengths)
    if not options:
        return None
    blocked = set(avoid)

    def score(option: tuple[int, ...]) -> tuple[int, float, tuple[int, ...]]:
        cuts = joints(option)
        clashes = sum(1 for cut in cuts if cut in blocked)
        spread = sum(abs(cut - length / 2) for cut in cuts)
        return (clashes, spread, option)

    return min(options, key=score)
