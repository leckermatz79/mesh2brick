# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Regression: the local LP time-limit patch (docs/UPSTREAM.md #2).

``stalled_lp.npz`` is a stability LP captured from legolization 0.5.0 (low-poly
bunny, 16 studs, slopes on) on which HiGHS presolve stalls indefinitely. With
the patch, the first attempt gives up after ``LP_ATTEMPT_TIME_LIMIT_S`` and
the presolve-free attempt solves it in a few seconds.
"""

from __future__ import annotations

import time
from pathlib import Path

import highspy
import numpy as np
import pytest
from legolization.stability import solver
from scipy import sparse
from scipy.optimize import linprog

from mesh2brick.backends.legolization import LP_ATTEMPT_TIME_LIMIT_S, TimeLimitedHighs

pytestmark = pytest.mark.slow

Lp = tuple[np.ndarray, sparse.csr_matrix, np.ndarray]


@pytest.fixture(scope="module")
def stalled_lp(fixtures_dir: Path) -> Lp:
    with np.load(fixtures_dir / "stalled_lp.npz") as data:
        matrix = sparse.csr_matrix(
            (data["a_data"], data["a_indices"], data["a_indptr"]),
            shape=tuple(int(n) for n in data["a_shape"]),
        )
        return data["c"], matrix, data["b"]


def test_patch_is_installed() -> None:
    attempts = solver._LP_ATTEMPTS
    assert all(o["time_limit"] == LP_ATTEMPT_TIME_LIMIT_S for _, o in attempts[:-1])
    assert attempts[-1][1] is None or "time_limit" not in attempts[-1][1]
    assert solver.highspy.Highs is TimeLimitedHighs
    assert solver.highspy.HighsLp is highspy.HighsLp  # everything else untouched


def test_scipy_path_solves_the_stalled_lp(stalled_lp: Lp) -> None:
    cost, a_ub, b_ub = stalled_lp
    started = time.perf_counter()
    result = None
    for method, options in solver._LP_ATTEMPTS:
        result = linprog(
            c=cost,
            A_ub=a_ub,
            b_ub=b_ub,
            bounds=(0, None),
            method=method,
            options=options,
        )
        if result.success:
            break
    assert result is not None
    assert result.success
    assert time.perf_counter() - started < 4 * LP_ATTEMPT_TIME_LIMIT_S


def test_direct_highspy_path_solves_the_stalled_lp(stalled_lp: Lp) -> None:
    """Mirrors legolization's ``_solve_lp_highspy`` attempt chain."""
    cost, a_ub, b_ub = stalled_lp
    rows, cols = a_ub.shape
    csc = a_ub.tocsc()
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = cols, rows
    lp.col_cost_ = cost
    lp.col_lower_ = np.zeros(cols)
    lp.col_upper_ = np.full(cols, np.inf)
    lp.row_lower_ = np.full(rows, -np.inf)
    lp.row_upper_ = b_ub
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = np.asarray(csc.indptr, dtype=np.int64)
    lp.a_matrix_.index_ = np.asarray(csc.indices, dtype=np.int64)
    lp.a_matrix_.value_ = csc.data
    engine = solver.highspy.Highs()
    engine.setOptionValue("output_flag", False)
    engine.setOptionValue("threads", 1)
    started = time.perf_counter()
    for presolve, method in (
        ("choose", "simplex"),
        ("off", "simplex"),
        ("choose", "ipm"),
    ):
        engine.setOptionValue("presolve", presolve)
        engine.setOptionValue("solver", method)
        engine.passModel(lp)
        engine.run()
        if engine.getModelStatus() == highspy.HighsModelStatus.kOptimal:
            break
    assert engine.getModelStatus() == highspy.HighsModelStatus.kOptimal
    assert time.perf_counter() - started < 4 * LP_ATTEMPT_TIME_LIMIT_S
