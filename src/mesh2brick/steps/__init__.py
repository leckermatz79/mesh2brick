# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Own build-step passes on top of the backend's sequencing (Phase 6, ADR 0012).

* :mod:`~mesh2brick.steps.structure`: which parts hold which (from cells).
* :mod:`~mesh2brick.steps.hanging`: place hanging parts with their holder.
* :mod:`~mesh2brick.steps.balance`: merge steps that are too small.
* :mod:`~mesh2brick.steps.metrics`: step sizes and hanging parts, measured.

The passes work on :class:`~mesh2brick.steps.plan.PlanStep` tuples with
backend ids, so they stay independent of any backend.
"""
