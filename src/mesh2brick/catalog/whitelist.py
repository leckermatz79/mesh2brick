# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Which parts placement may use: categories, whitelist and blacklist.

``parts.categories`` picks part families, ``parts.include`` (whitelist)
narrows them to the listed LDraw numbers, ``parts.exclude`` (blacklist)
removes parts. The backend states what it can place and which parts it
cannot do without (:class:`BackendRules`); impossible combinations are
rejected with a clear message (SPEC §4) instead of failing deep inside
placement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from mesh2brick.config import PartCategory, PartsConfig


class WhitelistError(ValueError):
    """``parts.*`` settings the backend cannot honour."""


@dataclass(frozen=True, slots=True)
class PlaceablePart:
    """A part the backend can place, with its family."""

    part: str
    category: PartCategory


@dataclass(frozen=True, slots=True)
class BackendRules:
    """Constraints of the placement backend on the part set."""

    required: frozenset[str] = frozenset()
    """Parts that must always be available (fillers for any shape)."""
    coupled: tuple[frozenset[str], ...] = ()
    """Groups the backend uses all together or not at all."""
    reasons: dict[str, str] = field(default_factory=dict)
    """Explanation per required part or group (keyed by part number)."""


@dataclass(frozen=True, slots=True)
class Whitelist:
    """The resulting part set plus notes worth showing."""

    parts: frozenset[str]
    notes: tuple[str, ...] = ()

    def categories(self, placeable: Sequence[PlaceablePart]) -> frozenset[PartCategory]:
        """Families that still have at least one allowed part."""
        return frozenset(p.category for p in placeable if p.part in self.parts)


def allowed_parts(
    placeable: Sequence[PlaceablePart],
    config: PartsConfig,
    rules: BackendRules,
    *,
    in_library: Callable[[str], bool],
) -> Whitelist:
    """Apply categories, include and exclude to the placeable parts.

    Raises:
        WhitelistError: for unknown or unplaceable part numbers, parts in
            disabled categories, excluded required parts and split groups.
    """
    by_part = {p.part: p for p in placeable}
    _check_numbers(by_part, config, in_library)
    enabled = set(config.categories)
    if off := [n for n in config.include if by_part[n].category not in enabled]:
        families = sorted({by_part[n].category for n in off})
        msg = (
            f"parts.include lists {', '.join(off)} from disabled categories "
            f"{', '.join(families)}; add them to parts.categories"
        )
        raise WhitelistError(msg)
    if blocked := sorted(rules.required & set(config.exclude)):
        msg = (
            f"parts.exclude cannot remove {', '.join(blocked)}: "
            f"{_reason(rules, blocked)}"
        )
        raise WhitelistError(msg)
    if config.include:
        chosen = set(config.include)
    else:
        chosen = {p.part for p in placeable if p.category in enabled}
    chosen -= set(config.exclude)
    notes: list[str] = []
    if added := sorted(rules.required - chosen):
        chosen |= set(added)
        notes.append(
            f"added {', '.join(added)} to parts.include: {_reason(rules, added)}"
        )
    for group in rules.coupled:
        family = {by_part[n].category for n in group if n in by_part}
        if not family & enabled:
            continue
        present = group & chosen
        if present and present != group:
            missing = sorted(group - present)
            msg = (
                f"parts {', '.join(sorted(group))} are used together or not at "
                f"all ({_reason(rules, sorted(group))}); missing: {', '.join(missing)}"
            )
            raise WhitelistError(msg)
    return Whitelist(parts=frozenset(chosen), notes=tuple(notes))


def _check_numbers(
    by_part: dict[str, PlaceablePart],
    config: PartsConfig,
    in_library: Callable[[str], bool],
) -> None:
    unknown = [n for n in (*config.include, *config.exclude) if n not in by_part]
    if not unknown:
        return
    missing = [n for n in unknown if not in_library(n)]
    if missing:
        msg = (
            f"unknown LDraw part number(s) {', '.join(missing)} in parts.include/"
            "exclude (not in the local LDraw library)"
        )
        raise WhitelistError(msg)
    msg = (
        f"part(s) {', '.join(unknown)} exist in LDraw but the placement backend "
        "cannot place them; `mesh2brick catalog list` shows the placeable parts"
    )
    raise WhitelistError(msg)


def _reason(rules: BackendRules, parts: Sequence[str]) -> str:
    reasons = dict.fromkeys(rules.reasons[p] for p in parts if p in rules.reasons)
    return "; ".join(reasons) or "the placement backend needs them"
