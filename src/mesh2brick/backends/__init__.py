# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Adapters to third-party LEGO libraries.

This package is the only place allowed to import ``legolization``,
``ldraw`` (pyldraw3) or ``rebrickable``; ``tests/test_architecture.py``
enforces that. Import the concrete backends lazily (they load large solver
stacks), the protocols eagerly.
"""

from mesh2brick.backends.protocols import (
    BackendError,
    Exporter,
    Placement,
    Placer,
    StabilityChecker,
    StabilityReport,
    StepSequencer,
)

__all__ = [
    "BackendError",
    "Exporter",
    "Placement",
    "Placer",
    "StabilityChecker",
    "StabilityReport",
    "StepSequencer",
]
