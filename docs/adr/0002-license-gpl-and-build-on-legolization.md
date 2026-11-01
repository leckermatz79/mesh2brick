# 2. GPL-3.0-or-later, built on legolization instead of re-implementing it

- Status: accepted
- Date: 2026-11-01

## Context

Turning a voxel model into a stable, buildable brick layout with build steps is a hard,
research-heavy problem (placement heuristics, rigid-block-equilibrium physics, repair,
sequencing). `legolization` (GPL-3.0-or-later) already solves it well. Version 0.5.0 has seven
placement strategies, an exact LP stability model, ALNS repair, smart step sequencing with
subassemblies, LDraw export via `pyldraw3`, and a reportlab instruction booklet. `pyldraw3`
and `rebrickable` from the same author are also GPL-3.0-or-later.

## Decision

mesh2brick is licensed **GPL-3.0-or-later** and uses `legolization`, `pyldraw3` and
`rebrickable` as regular, exactly pinned dependencies. It does not fork them. All imports of
these libraries are confined to `src/mesh2brick/backends/`, behind the protocols in
`backends/protocols.py`. Every other module works on mesh2brick's own data types
(`VoxelGrid`, `BrickModel`). A test enforces this rule. Generally useful improvements go
upstream as pull requests (collected in `docs/UPSTREAM.md`). Local patches are a stop-gap only,
and a fork is the product owner's call.

## Consequences

- We get a strong placement/physics/steps engine on day one. Our effort goes into what it
  lacks: mesh/CAD import, colour transfer, a wider catalogue, instruction quality, one
  config/CLI and the optional LLM layer.
- The GPL is required anyway by linking GPL libraries. All other dependencies must be
  GPL-compatible (checked in `docs/THIRD_PARTY.md`).
- Upstream releases can change behaviour. We pin exact versions, read changelogs before every
  upgrade, and our backend tests (smoke test, coordinate round trip) catch breaking changes.
- Swapping or forking the backend later only touches `backends/`.
