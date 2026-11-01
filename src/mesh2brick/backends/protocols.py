# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Backend interfaces: what the rest of mesh2brick may expect from a backend.

Only modules in :mod:`mesh2brick.backends` talk to third-party LEGO libraries.
Everything else talks to these protocols and to the backend-independent
:class:`~mesh2brick.model.BrickModel`. Swapping, forking or extending a backend
therefore stays local to this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from mesh2brick.config import Settings
    from mesh2brick.model import BrickModel
    from mesh2brick.voxel.grid import VoxelGrid


class BackendError(RuntimeError):
    """A backend could not do its job (missing data, invalid options, ...)."""


@dataclass(frozen=True, slots=True)
class StabilityReport:
    """Physics verdict for a placed model.

    Attributes:
        stable: every part is in static equilibrium.
        component_count: number of stud-connected part groups (1 = one piece).
        floating_count: parts not connected to the ground.
        max_score: worst per-part instability score (0 = perfectly stable).
        min_capacity_n: weakest connection's remaining friction capacity in N.
    """

    stable: bool
    component_count: int
    floating_count: int
    max_score: float
    min_capacity_n: float | None = None

    @property
    def buildable(self) -> bool:
        """Stable, one connected piece, and nothing floating."""
        return self.stable and self.component_count == 1 and self.floating_count == 0


@dataclass(frozen=True, slots=True)
class Placement:
    """A placed model plus its stability verdict.

    ``native`` is an opaque backend handle (e.g. legolization's result object)
    that lets the *same* backend export or re-sequence without a lossy round
    trip. Other code must not inspect it.
    """

    model: BrickModel
    stability: StabilityReport
    backend: str
    native: object | None = field(default=None, compare=False, repr=False)
    notes: tuple[str, ...] = ()
    """Things the user should know (e.g. a cheaper step plan was used)."""


@runtime_checkable
class Placer(Protocol):
    """Covers a voxel grid with parts."""

    name: str

    def strategies(self) -> tuple[str, ...]:
        """Placement strategies this backend offers."""
        ...

    def place(
        self,
        grid: VoxelGrid,
        settings: Settings,
        *,
        name: str = "model",
        deadline: float | None = None,
    ) -> Placement:
        """Place parts on ``grid`` (including repair and steps) by ``deadline``.

        ``deadline`` is a :func:`time.monotonic` timestamp; backends use cheaper
        methods as it approaches and report that in ``Placement.notes``.
        """
        ...


@runtime_checkable
class StabilityChecker(Protocol):
    """Judges whether a placed model holds together."""

    def check(self, placement: Placement, settings: Settings) -> StabilityReport:
        """Return the physics verdict for ``placement``."""
        ...


@runtime_checkable
class StepSequencer(Protocol):
    """Orders parts into build steps."""

    def sequence(self, placement: Placement, settings: Settings) -> Placement:
        """Return ``placement`` with freshly computed build steps."""
        ...


@runtime_checkable
class Exporter(Protocol):
    """Writes LDraw files."""

    def write_ldraw(self, placement: Placement, path: Path) -> Path:
        """Write ``.ldr``/``.mpd`` (by suffix) with ``0 STEP`` markers."""
        ...
