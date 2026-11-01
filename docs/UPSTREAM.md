# Upstream contributions

Generally useful improvements go upstream as pull requests instead of local patches
(see ADR 0002). Upstream PRs are only opened **after the product owner approves**.
Until then a draft (branch + PR text) is prepared and linked here.

Status values: `idea` → `draft ready` → `approved` → `opened` → `merged` / `declined`.

## Local patches in use

None.

## Candidates

| # | Project | Topic | Why | Status | Link |
|---|---|---|---|---|---|
| 1 | legolization | Ship a `py.typed` marker (PEP 561) | The package is fully annotated but type checkers ignore it without the marker. We currently work around it with a mypy override (`follow_untyped_imports`). One-line change in the package data. | idea | – |
