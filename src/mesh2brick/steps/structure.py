# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Which parts hold which: stud connections derived from occupied cells only.

Two parts are connected when one sits directly on top of the other in at
least one stud column (the upper part's lowest cell in that column is one
plate above the lower part's highest cell there). Tiles have a smooth top,
so nothing connects onto them. Slopes count as studded on top, which
overstates their grip slightly (they are opt-in and rare).

A part is *grounded* in a set of parts if a chain of connections inside the
set leads down to the model's lowest layer (the table).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

Cell = tuple[int, int, int]
Column = tuple[int, int]
SMOOTH_TOP: Final = frozenset({"tile"})


@dataclass(frozen=True, slots=True)
class Structure:
    """Stud connections between parts (keyed by any hashable int id).

    Attributes:
        below: per part, the parts it rests on.
        above: per part, the parts resting on it.
        on_table: parts standing on the lowest layer.
        cells: per part, its occupied cells.
    """

    below: Mapping[int, frozenset[int]]
    above: Mapping[int, frozenset[int]]
    on_table: frozenset[int]
    cells: Mapping[int, frozenset[Cell]]

    @classmethod
    def from_cells(
        cls,
        cells: Mapping[int, Iterable[Cell]],
        categories: Mapping[int, str] | None = None,
    ) -> Structure:
        """Derive the connections of parts given their cells (and families)."""
        frozen = {part: frozenset(c) for part, c in cells.items()}
        if any(not c for c in frozen.values()):
            msg = "every part needs at least one cell"
            raise ValueError(msg)
        tops: dict[Cell, int] = {}
        bottoms: dict[Cell, int] = {}
        for part, part_cells in frozen.items():
            columns: dict[Column, list[int]] = {}
            for x, y, z in part_cells:
                columns.setdefault((x, y), []).append(z)
            smooth = (categories or {}).get(part) in SMOOTH_TOP
            for (x, y), zs in columns.items():
                bottoms[(x, y, min(zs))] = part
                if not smooth:
                    tops[(x, y, max(zs))] = part
        below: dict[int, set[int]] = {part: set() for part in frozen}
        above: dict[int, set[int]] = {part: set() for part in frozen}
        for (x, y, z), lower in tops.items():
            upper = bottoms.get((x, y, z + 1))
            if upper is not None and upper != lower:
                below[upper].add(lower)
                above[lower].add(upper)
        floor = min(z for c in frozen.values() for _, _, z in c) if frozen else 0
        on_table = frozenset(
            part
            for part, part_cells in frozen.items()
            if min(z for _, _, z in part_cells) == floor
        )
        return cls(
            below={p: frozenset(s) for p, s in below.items()},
            above={p: frozenset(s) for p, s in above.items()},
            on_table=on_table,
            cells=frozen,
        )

    def neighbours(self, part: int) -> frozenset[int]:
        """Parts directly connected to ``part`` (above or below)."""
        return self.below[part] | self.above[part]

    def grounded(self, parts: Iterable[int]) -> frozenset[int]:
        """The members of ``parts`` with a connection chain to the table."""
        subset = set(parts)
        reached = {p for p in subset if p in self.on_table}
        stack = list(reached)
        while stack:
            current = stack.pop()
            for other in self.neighbours(current):
                if other in subset and other not in reached:
                    reached.add(other)
                    stack.append(other)
        return frozenset(reached)

    def floating(self, parts: Iterable[int]) -> frozenset[int]:
        """The members of ``parts`` that would hang in the air on their own."""
        subset = frozenset(parts)
        return subset - self.grounded(subset)

    def components(self, parts: Iterable[int]) -> list[frozenset[int]]:
        """Connected groups among ``parts`` (deterministic order)."""
        remaining = set(parts)
        groups: list[frozenset[int]] = []
        while remaining:
            seed = min(remaining)
            remaining.discard(seed)
            group = {seed}
            stack = [seed]
            while stack:
                current = stack.pop()
                for other in self.neighbours(current):
                    if other in remaining:
                        remaining.discard(other)
                        group.add(other)
                        stack.append(other)
            groups.append(frozenset(group))
        return groups

    def columns(self, parts: Iterable[int]) -> dict[Column, tuple[int, int]]:
        """Lowest and highest layer per stud column covered by ``parts``."""
        span: dict[Column, tuple[int, int]] = {}
        for part in parts:
            for x, y, z in self.cells[part]:
                low, high = span.get((x, y), (z, z))
                span[(x, y)] = (min(low, z), max(high, z))
        return span

    def share_columns(self, first: Iterable[int], second: Iterable[int]) -> bool:
        """Whether the two part sets stack in at least one stud column."""
        return not self.columns(first).keys().isdisjoint(self.columns(second))

    def hidden_share(self, part: int, cover: Iterable[int]) -> float:
        """Share of ``part``'s stud columns that parts of ``cover`` lie above."""
        own = self.columns([part])
        top = {column: high for column, (_, high) in own.items()}
        covered = {
            (x, y)
            for other in cover
            if other != part
            for x, y, z in self.cells[other]
            if (x, y) in top and z > top[(x, y)]
        }
        return len(covered) / len(own)

    def blocked_from_above(self, parts: Iterable[int], placed: Iterable[int]) -> bool:
        """Whether a part of ``placed`` lies above ``parts`` in one of their columns.

        Then ``parts`` cannot be lowered into place from above as one piece.
        """
        span = self.columns(parts)
        return any(
            (x, y) in span and z > span[(x, y)][1]
            for part in placed
            for x, y, z in self.cells[part]
        )
