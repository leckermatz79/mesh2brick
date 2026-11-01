# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Shared fixtures.

Tests marked ``ldraw`` need the LDraw parts library. Locally they are skipped
when it is missing; in CI (``MESH2BRICK_REQUIRE_LDRAW=1``) a missing library is
an error, so the smoke test can never silently disappear.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.helpers import make_brick

from mesh2brick.backends.pyldraw import SETUP_HINT, library_status
from mesh2brick.model import BrickModel, BuildStep, ColorInfo

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True, scope="session")
def _private_cache(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Keep the part-spec cache out of the user's real cache directory."""
    os.environ["MESH2BRICK_CACHE_DIR"] = str(tmp_path_factory.mktemp("cache"))


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    del config
    if not any(item.get_closest_marker("ldraw") for item in items):
        return
    if library_status().ready:
        return
    if os.environ.get("MESH2BRICK_REQUIRE_LDRAW") == "1":
        msg = f"LDraw library required but missing; {SETUP_HINT}"
        raise pytest.UsageError(msg)
    skip = pytest.mark.skip(reason=f"LDraw library missing; {SETUP_HINT}")
    for item in items:
        if item.get_closest_marker("ldraw"):
            item.add_marker(skip)


@pytest.fixture
def sample_model() -> BrickModel:
    """Two 2x4 bricks side by side with a 2x2 on top (two steps)."""
    return BrickModel(
        name="tower",
        parts=(
            make_brick("3001", 0, 0, 0, 0),
            make_brick("3001", 2, 0, 0, 0),
            make_brick("3003", 1, 1, 3, 1, w=2, d=2),
        ),
        steps=(BuildStep(), BuildStep()),
        colors={4: ColorInfo(name="Red", rgb_hex="#c91a09")},
        source="test",
    )
