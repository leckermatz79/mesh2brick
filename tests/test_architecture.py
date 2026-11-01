# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Project rules from SPEC.md / CLAUDE.md that a machine can check."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "mesh2brick"
BACKENDS = PACKAGE / "backends"
THIRD_PARTY_LEGO = ("legolization", "ldraw", "rebrickable")
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later"


def _python_files(*roots: Path) -> list[Path]:
    return sorted(p for root in roots for p in root.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize(
    "path",
    [p for p in _python_files(PACKAGE) if BACKENDS not in p.parents],
    ids=lambda p: str(p.relative_to(PACKAGE)),
)
def test_only_backends_import_lego_libraries(path: Path) -> None:
    offending = sorted(
        module
        for module in _imported_modules(path)
        if module.split(".")[0] in THIRD_PARTY_LEGO
    )
    assert not offending, f"{path.name} imports {offending}; use mesh2brick.backends"


@pytest.mark.parametrize(
    "path",
    _python_files(PACKAGE, ROOT / "tests", ROOT / "scripts"),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_every_python_file_has_spdx_header(path: Path) -> None:
    head = path.read_text(encoding="utf-8").splitlines()[:3]
    assert SPDX in head, f"{path.relative_to(ROOT)} lacks the SPDX header"


def test_backend_dependencies_are_pinned_exactly() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for name in ("legolization", "pyldraw3", "rebrickable"):
        assert f'"{name}==' in text, f"{name} must be pinned with =="
