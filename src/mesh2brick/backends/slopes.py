# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The slope pass on a legolization layout (ROADMAP 8, ADR 0021).

The voxelizer rates every possible slope against the input mesh
(:mod:`mesh2brick.voxel.slopes`), :func:`mesh2brick.place.slopes.slope_sites`
orders the good ones; :func:`apply_slopes` puts them into the placed model:
it cuts the bricks and plates under a slope, rebuilds what is left of them
from parts of the same family, keeps the model one piece and joins the pieces
with their neighbours again. The stability check of the finished model is
the backend's (:meth:`mesh2brick.backends.legolization.LegolizationBackend.place`).
"""

from __future__ import annotations

import dataclasses
import math
from collections import Counter, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from legolization.catalog import Catalog, Category, default_catalog
from legolization.color import default_palette
from legolization.layout import CollisionError

from mesh2brick.backends.layout_ops import (
    place_exact,
    produced_in,
    rect_dims,
    rect_keys,
)
from mesh2brick.place.tiles import rect_cover
from mesh2brick.voxel.grid import PLATES_PER_BRICK

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from legolization.layout import Layout, PlacedBrick

    from mesh2brick.model import Cell
    from mesh2brick.place.slopes import SlopeSite
    from mesh2brick.place.tiles import Column

RECOMMENDED_SLOPE_TIME: Final = "10min"

SLOPES_TIME_NOTE: Final = (
    f"slopes skipped: time limit; recommended --time {RECOMMENDED_SLOPE_TIME}"
)
SLOPES_UNDONE_NOTE: Final = (
    "slopes undone: with them the model would no longer hold together"
)
MAX_SLOPE_COST: Final = 2
"""Parts a slope may add (it replaces the parts it cuts by itself and what is
left of them): two pieces of a cut brick, say. Dearer stairs keep their step
(bunny: 129 instead of 140 slopes, +14 % instead of +18 % parts, deviation
1.78 instead of 1.76 mm; issue #51)."""
SLOPE_PARTS_GUIDE: Final = 0.15
"""Slopes that add more parts than this share of the model are reported, not
taken back (the guide of the tiles, issue #51)."""


@dataclass(frozen=True, slots=True)
class SlopeReport:
    """What :func:`apply_slopes` changed (ROADMAP 8, ADR 0021)."""

    placed: dict[str, int] = dataclasses.field(default_factory=dict)
    """Slopes placed, per LDraw part."""
    cut: int = 0
    """Sloped columns that cut the edge off a stair (on a filled cell)."""
    filled: int = 0
    """Sloped columns that fill the corner of a stair (material beyond the
    voxels, where the mesh is)."""
    added: int = 0
    """Parts added: the slopes and the pieces left of the parts cut for them,
    minus the parts cut."""
    colour: dict[int, int] = dataclasses.field(default_factory=dict)
    """Stairs (stud cells) that keep their step because LEGO does not make a
    slope that would fit there in their colour, per colour (for ROADMAP 12)."""
    missing: dict[int, tuple[str, ...]] = dataclasses.field(default_factory=dict)
    """Per colour of :attr:`colour`: the slopes LEGO does not make in it."""
    blocked: int = 0
    """Sites that stay stairs because the parts there cannot make room (a part
    of another family, the pieces would not hold together, no fitting part)."""
    costly: int = 0
    """Stairs (stud cells) that keep their step because a slope there would
    add more than :attr:`max_cost` parts."""
    max_cost: int | None = MAX_SLOPE_COST
    limited: int = 0
    """Stairs (stud cells) that keep their step because the parts limit was
    reached (:attr:`max_share`, ``parts.slopes_max_share``)."""
    max_share: float | None = None
    joined: int = 0
    """Parts saved by joining pieces with their neighbours (in :attr:`added`)."""

    @property
    def count(self) -> int:
        """Slopes placed."""
        return sum(self.placed.values())

    @property
    def colour_sites(self) -> int:
        """Stairs kept for want of the colour."""
        return sum(self.colour.values())

    def summary(self) -> str:
        """One line for the user."""
        kinds = ", ".join(f"{n} x {part}" for part, n in sorted(self.placed.items()))
        text = f"slopes on tilted stairs: {self.count}" + (
            f" ({kinds})" if kinds else ""
        )
        if self.added:
            text += f", +{self.added} parts"
        if self.filled:
            text += f"; {self.filled} sloped column(s) fill a stair corner"
        if self.costly:
            text += (
                f"; {self.costly} stair(s) keep their step: a slope would add more "
                f"than {self.max_cost} parts there"
            )
        if self.limited:
            limit = "" if self.max_share is None else f" (+{self.max_share:.0%})"
            text += (
                f"; {self.limited} stair(s) keep their step: parts limit{limit} "
                "reached, the slopes that bring the model closest came first"
            )
        if self.colour:
            palette = default_palette()
            missing = "; ".join(
                f"{', '.join(self.missing[code])} not in colour {code} "
                f"({palette.name_of(code)})"
                for code in sorted(self.colour)
            )
            text += (
                f"; {self.colour_sites} stair(s) keep their steps for want of the "
                f"colour ({missing}; ROADMAP 12)"
            )
        return text


def apply_slopes(
    layout: Layout,
    sites: Sequence[SlopeSite],
    *,
    allowed: frozenset[str] | None = None,
    slopes: frozenset[str] | None = None,
    produced: Callable[[str, int], bool | None] = produced_in,
    max_cost: int | None = MAX_SLOPE_COST,
    max_added: int | None = None,
) -> SlopeReport:
    """Put slopes on the stairs ``sites`` ask for, best first (ADR 0021).

    A slope takes a layer of three plates over its columns. Its stud columns
    and the sloped columns on a filled cell are cut out of the bricks and
    plates there (what is left of them becomes parts of the same family and
    height); a sloped column on an empty cell needs a part with a stud right
    below it. Nothing may lie on a sloped column. A site stays a stair when a
    cell is taken by a part of another family (a tile, a slope placed before),
    when the parts there have more than one colour, when the pieces would not
    hold together, or when LEGO does not make the slope (or a piece) in that
    colour, or when the slope would add more than ``max_cost`` parts (the
    slope and the pieces minus the parts cut; ``None``: no limit) or take the
    parts added so far beyond ``max_added`` (``parts.slopes_max_share``;
    ``None``: no limit). Pieces come
    from ``allowed``, slopes from ``slopes`` (LDraw numbers, ``None``: any; the
    slopes need not be in the layout's catalogue, they are added to it).
    Changes ``layout`` in place.
    """
    layout.catalog = with_slopes(layout.catalog)
    keys = _slope_keys(layout.catalog, slopes)
    placed: Counter[str] = Counter()
    wanting: dict[Cell, tuple[int, str]] = {}
    dear: set[Cell] = set()
    held_back: set[Cell] = set()
    counts: Counter[str] = Counter()
    taken: set[Cell] = set()
    pieces: set[int] = set()
    for site in sites:
        key = keys.get(site.part)
        cells = _site_cells(site)
        if key is None or cells & taken:
            continue
        plan = _plan_slope(layout, site, cells, allowed=allowed, produced=produced)
        if isinstance(plan, _SlopePlan) and plan.missing:
            for x, y in site.studs:
                wanting.setdefault((x, y, site.layer), (plan.colour, site.part))
            continue
        if (
            max_cost is not None
            and not isinstance(plan, str)
            and 1 + len(plan.pieces) - len(plan.donors) > max_cost
        ):
            dear.update((x, y, site.layer) for x, y in site.studs)
            continue
        if (
            max_added is not None
            and not isinstance(plan, str)
            and counts["added"] + 1 + len(plan.pieces) - len(plan.donors) > max_added
        ):
            held_back.update((x, y, site.layer) for x, y in site.studs)
            continue
        added = None if isinstance(plan, str) else _apply_slope(layout, key, site, plan)
        if added is None or isinstance(plan, str):
            counts["blocked"] += 1
            continue
        taken |= cells
        placed[site.part] += 1
        pieces.update(added[1:])
        counts["cut"] += plan.cut
        counts["filled"] += plan.filled
        counts["added"] += len(added) - len(plan.donors)
    joined = _merge_pieces(layout, pieces, allowed=allowed, produced=produced)
    counts["added"] -= joined
    bottom = {(x, y, z // PLATES_PER_BRICK) for x, y, z in taken}
    kept = {cell: got for cell, got in wanting.items() if cell not in bottom}
    colour = Counter(code for code, _ in kept.values())
    missing: dict[int, set[str]] = {}
    for code, part in kept.values():
        missing.setdefault(code, set()).add(part)
    return SlopeReport(
        placed=dict(sorted(placed.items())),
        cut=counts["cut"],
        filled=counts["filled"],
        added=counts["added"],
        colour=dict(sorted(colour.items())),
        missing={code: tuple(sorted(parts)) for code, parts in sorted(missing.items())},
        blocked=counts["blocked"],
        costly=len(dear - bottom),
        max_cost=max_cost,
        limited=len(held_back - bottom - dear),
        joined=joined,
    )


def apply_slopes_within(
    layout: Layout,
    sites: Sequence[SlopeSite],
    *,
    max_share: float | None,
    allowed: frozenset[str] | None = None,
    slopes: frozenset[str] | None = None,
    produced: Callable[[str, int], bool | None] = produced_in,
) -> SlopeReport:
    """:func:`apply_slopes` adding at most ``max_share`` of the layout's parts.

    The best slopes come first; once the limit is reached the other stairs
    keep their steps (``parts.slopes_max_share``, product owner 2026-11-16:
    +15 %). Pieces joined with their neighbours give parts back, so the pass
    is tried without a limit first (a model under the limit is not touched
    by it), then with the largest running limit that ends within it.
    ``None``: no limit. Changes ``layout`` in place.
    """
    kwargs: dict[str, Any] = {
        "allowed": allowed,
        "slopes": slopes,
        "produced": produced,
    }
    if max_share is None:
        return apply_slopes(layout, sites, **kwargs)
    limit = math.floor(max_share * len(layout))
    trial = layout.copy()
    report = apply_slopes(trial, sites, **kwargs)
    if report.added > limit:
        low, high = limit, report.added + report.joined
        best: tuple[Layout, SlopeReport] | None = None
        while low <= high:
            middle = (low + high) // 2
            attempt = layout.copy()
            found = apply_slopes(attempt, sites, max_added=middle, **kwargs)
            if found.added <= limit:
                best, low = (attempt, found), middle + 1
            else:
                high = middle - 1
        if best is None:  # cannot happen: running limit = limit ends within it
            attempt = layout.copy()
            best = attempt, apply_slopes(attempt, sites, max_added=limit, **kwargs)
        trial, report = best
    layout.catalog = trial.catalog
    layout.replace_with(trial)
    return dataclasses.replace(report, max_share=max_share)


@dataclass(frozen=True, slots=True)
class _SlopePlan:
    """How one slope fits (nothing changed yet)."""

    colour: int
    donors: tuple[PlacedBrick, ...]
    pieces: tuple[tuple[str, frozenset[Cell], int], ...]
    cut: int = 0
    filled: int = 0
    missing: bool = False
    """LEGO does not make the slope in ``colour``."""
    near: dict[int, frozenset[Cell]] = dataclasses.field(default_factory=dict)
    """Parts right below or above the donors, and the parts the sloped columns
    rest on: they must stay connected."""
    local: bool = True
    """They stay connected through the slope and the pieces alone."""


def _site_cells(site: SlopeSite) -> frozenset[Cell]:
    """The plate cells a slope at ``site`` takes (one brick height)."""
    low = PLATES_PER_BRICK * site.layer
    return frozenset(
        (x, y, z) for x, y in site.columns for z in range(low, low + PLATES_PER_BRICK)
    )


def with_slopes(catalog: Catalog) -> Catalog:
    """``catalog`` plus legolization's slopes (kept out of placement by colour).

    With ``parts.availability: exclude`` a slope LEGO does not make in one of
    the model's colours leaves the placement catalogue; the slope pass checks
    colours one slope at a time and needs them back.
    """
    full = default_catalog()
    extra = {
        key: part
        for key, part in full.parts.items()
        if part.category is Category.SLOPE and key not in catalog.parts
    }
    return Catalog(parts={**catalog.parts, **extra}) if extra else catalog


def _slope_keys(catalog: Catalog, allowed: frozenset[str] | None) -> dict[str, str]:
    """LDraw number -> catalogue key of every usable slope."""
    return {
        part.ldraw_part: key
        for key, part in sorted(catalog.parts.items())
        if part.category is Category.SLOPE
        and (allowed is None or part.ldraw_part in allowed)
    }


def _plan_slope(
    layout: Layout,
    site: SlopeSite,
    cells: frozenset[Cell],
    *,
    allowed: frozenset[str] | None,
    produced: Callable[[str, int], bool | None],
) -> _SlopePlan | str:
    """Plan one slope on ``cells``; a reason string when it does not fit."""
    found = _slope_donors(layout, site)
    if isinstance(found, str):
        return found
    donors, cut, filled = found
    colours = {donor.colour_code for donor in donors.values()}
    if len(colours) != 1:
        return "colours"
    code = colours.pop()
    if produced(site.part, code) is False:
        return _SlopePlan(code, (), (), missing=True)
    pieces: list[tuple[str, frozenset[Cell], int]] = []
    for donor in donors.values():
        part = layout.part_of(donor)
        rest = {(x, y) for x, y, _ in layout.cells_of(donor)} - site.columns
        if not rest:
            continue
        same = rect_keys(
            layout, part.category, part.height_plates,
            colour=code, allowed=allowed, produced=produced,
        )  # fmt: skip
        cover = rect_cover(rest, same.keys())
        if cover is None:
            return "cover"
        z0 = donor.layer
        z1 = z0 + part.height_plates
        for size, columns in cover:
            if not _touches_any(layout, donors, columns, (z0 - 1, z1)):
                return "hangs"  # the piece would hang on nothing
            piece = frozenset((x, y, z) for x, y in columns for z in range(z0, z1))
            pieces.append((same[size], piece, z0))
    near = _near_parts(layout, tuple(donors.values()), site, cells)
    local = _holds_together(pieces, cells, near)
    return _SlopePlan(
        code, tuple(donors.values()), tuple(pieces), cut, filled, near=near, local=local
    )


def _slope_donors(  # noqa: PLR0911 - every way a site can fail, spelled out
    layout: Layout, site: SlopeSite
) -> tuple[dict[int, PlacedBrick], int, int] | str:
    """The bricks and plates a slope replaces, its cut and filled columns.

    A reason string when the site does not fit: a stud column must be filled,
    a sloped column on an empty cell must rest on a stud, nothing may rest on
    a sloped column, and the parts cut must be bricks or plates within the
    slope's three plates.
    """
    bottom = PLATES_PER_BRICK * site.layer
    top = bottom + PLATES_PER_BRICK - 1
    donors: dict[int, PlacedBrick] = {}
    cut = filled = 0
    for x, y in site.columns:
        found = [layout.brick_at((x, y, z)) for z in range(bottom, top + 1)]
        if all(f is None for f in found):
            if (x, y) in site.studs:
                return "stud-empty"
            below = layout.brick_at((x, y, bottom - 1))
            if below is None or (x, y, bottom - 1) not in {
                c.cell for c in layout.connectors_of(below, top=True)
            }:
                return "no-support"
            filled += 1
        elif any(f is None for f in found):
            return "mixed"
        else:
            cut += (x, y) in site.sloped
            donors.update((f.brick_id, f) for f in found if f is not None)
        if (x, y) in site.sloped and layout.brick_at((x, y, top + 1)) is not None:
            return "covered"
    for donor in donors.values():
        part = layout.part_of(donor)
        if part.category not in (Category.BRICK, Category.PLATE):
            return "family"
        if rect_dims(part) is None:
            return "shape"
        if donor.layer < bottom or max(c[2] for c in layout.cells_of(donor)) > top:
            return "layers"
    return donors, cut, filled


def _touches_any(
    layout: Layout,
    donors: Mapping[int, PlacedBrick],
    columns: frozenset[Column],
    layers: tuple[int, ...],
) -> bool:
    """Some part other than ``donors`` lies right below or above ``columns``."""
    return any(
        (found := layout.brick_at((x, y, z))) is not None
        and found.brick_id not in donors
        for x, y in columns
        for z in layers
    )


def _near_parts(
    layout: Layout,
    donors: tuple[PlacedBrick, ...],
    site: SlopeSite,
    cells: frozenset[Cell],
) -> dict[int, frozenset[Cell]]:
    """Parts right below or above the donors, and those the slope rests on."""
    ids = {donor.brick_id for donor in donors}
    near: dict[int, frozenset[Cell]] = {}
    for donor in donors:
        mine = layout.cells_of(donor)
        low, high = min(c[2] for c in mine) - 1, max(c[2] for c in mine) + 1
        for x, y, _ in mine:
            for z in (low, high):
                found = layout.brick_at((x, y, z))
                if found is not None and found.brick_id not in ids:
                    near[found.brick_id] = frozenset(layout.cells_of(found))
    bottom = min(c[2] for c in cells)
    for x, y in site.columns:
        found = layout.brick_at((x, y, bottom - 1))
        if found is not None and found.brick_id not in ids:
            near[found.brick_id] = frozenset(layout.cells_of(found))
    return near


def _holds_together(
    pieces: Sequence[tuple[str, frozenset[Cell], int]],
    slope: frozenset[Cell],
    near: Mapping[int, frozenset[Cell]],
) -> bool:
    """The ``near`` parts hang together through the slope and the pieces alone.

    As for a cut tile (:func:`_stays_together`). Nothing rests on the sloped
    columns (:func:`_plan_slope` makes sure), so every vertical contact is a
    stud connection.
    """
    groups = [slope, *(piece for _, piece, _ in pieces), *near.values()]
    owner = {cell: i for i, group in enumerate(groups) for cell in group}
    parent = list(range(len(groups)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, group in enumerate(groups):
        for x, y, z in group:
            for other in (owner.get((x, y, z - 1)), owner.get((x, y, z + 1))):
                if other is not None and other != i:
                    parent[root(i)] = root(other)
    return len({root(i) for i in range(len(groups))}) == 1


def _joined(layout: Layout, reach: set[int]) -> bool:
    """The parts ``reach`` are still connected, if need be the long way round.

    Breadth-first over parts stacked on each other (a stud connection),
    starting at one of them, until all are found: the model stays one piece.
    Whether it also stays strong enough the stability check of the finished
    model decides (:meth:`LegolizationBackend._check_finish`).
    """
    if not reach:
        return True
    start = min(reach)
    seen = {start}
    queue = deque([start])
    while queue:
        brick = layout.bricks[queue.popleft()]
        for x, y, z in layout.cells_of(brick):
            for dz in (-1, 1):
                found = layout.brick_at((x, y, z + dz))
                if found is not None and found.brick_id not in seen:
                    seen.add(found.brick_id)
                    queue.append(found.brick_id)
        if reach <= seen:
            return True
    return reach <= seen


def _slope_pose(
    part: Any, studs: frozenset[Column], columns: frozenset[Column], layer: int
) -> tuple[int, int, int] | None:
    """``(x, y, yaw)`` placing a slope's studs on ``studs`` and body on ``columns``."""
    tx = min(c[0] for c in columns)
    ty = min(c[1] for c in columns)
    for yaw in part.orientations:
        cells = part.cells_at(0, 0, layer, yaw)
        x = tx - min(c[0] for c in cells)
        y = ty - min(c[1] for c in cells)
        body = {(c[0], c[1]) for c in part.cells_at(x, y, layer, yaw)}
        tops = {
            (c.cell[0], c.cell[1])
            for c in part.connectors_at(x, y, layer, yaw, top=True)
        }
        if body == columns and tops == studs:
            return x, y, yaw
    return None


def _apply_slope(
    layout: Layout, key: str, site: SlopeSite, plan: _SlopePlan
) -> list[int] | None:
    """Carry out a slope plan: the new ids (slope first), ``None`` if it does not fit.

    The parts around must stay connected (:func:`_joined`); otherwise nothing
    changes.
    """
    part = layout.catalog[key]
    layer = PLATES_PER_BRICK * site.layer
    pose = _slope_pose(part, frozenset(site.studs), site.columns, layer)
    if pose is None:
        return None
    removed = layout.remove_many(donor.brick_id for donor in plan.donors)
    added: list[int] = []
    try:
        added.append(
            layout.add(key, pose[0], pose[1], layer, pose[2], plan.colour).brick_id
        )
    except CollisionError:
        added = []
    else:
        for piece_key, target, z in plan.pieces:
            new = place_exact(layout, piece_key, target, z, plan.colour)
            if new is None:
                break
            added.append(new)
        else:
            if plan.local or _joined(layout, {*plan.near, *added}):
                return added
    _undo_slope(layout, added, removed)
    return None


def _undo_slope(layout: Layout, added: list[int], removed: list[PlacedBrick]) -> None:
    """Put the parts a slope replaced back."""
    layout.remove_many(added)
    for brick in removed:
        layout.add(
            brick.part_key, brick.x, brick.y, brick.layer, brick.yaw, brick.colour_code
        )


def _merge_pieces(
    layout: Layout,
    seeds: set[int],
    *,
    allowed: frozenset[str] | None,
    produced: Callable[[str, int], bool | None],
) -> int:
    """Join the pieces left of cut parts with neighbours into bigger parts.

    Two bricks (or plates) side by side, on the same layer, of one height and
    colour, whose tops together form a rectangle LEGO makes in that colour,
    become one part; merged parts may merge again. Returns the parts saved.
    """
    saved = 0
    todo = sorted(seeds)
    while todo:
        brick_id = todo.pop(0)
        brick = layout.bricks.get(brick_id)
        if brick is None:
            continue
        merged = _merge_once(layout, brick, allowed=allowed, produced=produced)
        if merged is not None:
            saved += 1
            todo.append(merged)
    return saved


def _merge_once(
    layout: Layout,
    brick: PlacedBrick,
    *,
    allowed: frozenset[str] | None,
    produced: Callable[[str, int], bool | None],
) -> int | None:
    """Merge ``brick`` with one side neighbour (lowest id first); the new id."""
    part = layout.part_of(brick)
    if part.category not in (Category.BRICK, Category.PLATE) or not rect_dims(part):
        return None
    mine = layout.cells_of(brick)
    columns = {(x, y) for x, y, _ in mine}
    others = sorted(
        {
            found.brick_id
            for x, y, z in mine
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if (found := layout.brick_at((x + dx, y + dy, z))) is not None
            and found.brick_id != brick.brick_id
        }
    )
    sizes = rect_keys(
        layout, part.category, part.height_plates,
        colour=brick.colour_code, allowed=allowed, produced=produced,
    )  # fmt: skip
    for other_id in others:
        other = layout.bricks[other_id]
        if (
            other.layer != brick.layer
            or other.colour_code != brick.colour_code
            or layout.part_of(other).category is not part.category
            or layout.part_of(other).height_plates != part.height_plates
        ):
            continue
        union = columns | {(x, y) for x, y, _ in layout.cells_of(other)}
        cover = rect_cover(union, sizes.keys())
        if cover is None or len(cover) != 1:
            continue
        size, _ = cover[0]
        target = frozenset(
            (x, y, z)
            for x, y in union
            for z in range(brick.layer, brick.layer + part.height_plates)
        )
        removed = layout.remove_many((brick.brick_id, other_id))
        new = place_exact(layout, sizes[size], target, brick.layer, brick.colour_code)
        if new is not None:
            return new
        for old in removed:
            layout.add(old.part_key, old.x, old.y, old.layer, old.yaw, old.colour_code)
        return None
    return None
