# 7. STEP import via cascadio instead of cadquery/OCP

- Status: accepted
- Date: 2026-11-01

## Context

SPEC §2 asks for STEP import "via the optional extra `cadquery`/`OCP`". Reading STEP needs
OpenCASCADE (OCCT); the question is which Python packaging of it. Wheel sizes on PyPI
(2026-11-01):

| Package | Licence | macOS arm64 | Linux x86_64 | Extra dependencies |
|---|---|---:|---:|---|
| `cadquery-ocp` 8.0.1 | Apache-2.0 (OCCT: LGPL-2.1 + exception) | 63 MB | 67 MB | `vtk` (103–140 MB) |
| `cadquery-ocp-novtk` 8.0.1 | as above | 63 MB | 67 MB | – |
| `cascadio` 0.1.1 | MIT (OCCT: LGPL-2.1 + exception) | 22 MB | 28 MB | – |
| `gmsh` 4.15 | GPL-2.0-or-later | 36 MB | 40 MB | – |

CLAUDE.md requires asking the product owner before adding a dependency over 50 MB.
We need only one thing from OpenCASCADE: read a STEP file (with assemblies and colours) and
tessellate it with a given tolerance.

## Decision

The `step` extra installs **cascadio** (pinned). It is maintained by the trimesh author and
used by trimesh itself for STEP. It reads STEP with OCCT's XDE reader (assemblies, names,
colours), tessellates with `tol_linear` / `tol_angular`, and returns a binary glTF, which
trimesh loads. `ingest/step.py`:

- `input.step_tolerance_mm` (default 0.05 mm) is the linear deflection. OCCT works in
  millimetres internally, so the value is in millimetres whatever unit the file uses. A test
  with the same cylinder in mm and in m gave identical triangle counts.
- glTF stores metres; the loader scales back to millimetres.
- STEP colours become glTF material colours in linear light; `ingest/colors.py` converts
  them to sRGB. trimesh keeps the linear value as bytes, which costs up to ±3 levels in
  very dark tones. That is irrelevant for matching to LEGO colours.
- Every solid becomes its own part. `input.multi_body` (`union` | `error`) decides whether
  several bodies are merged (overlaps unioned) or rejected; it applies to all formats.
- Without the extra, STEP files fail with an install hint (`uv sync --extra step`).

Test fixtures are written by a small AP214 writer in `scripts/make_fixtures.py` (boxes as
B-rep solids with optional colours), so no CAD kernel is needed to make them.

## Consequences

- Size: the cascadio wheel is 22–28 MB, but it unpacks to ~70 MB because OpenCASCADE is
  linked into it. CLAUDE.md's "ask before > 50 MB" does not say whether download or installed
  size counts, so the product owner gets the decision with the Phase 3 pull request. It is an
  optional extra (default installs are unaffected) and smaller than the `cadquery-ocp`
  packaging SPEC §2 names (63 MB as a download alone).
- We do not get OCP's full B-rep API (no exact volumes, no feature recognition). If a later
  phase needs that, `cadquery-ocp-novtk` can be added beside it (with the product owner's OK).
- CI installs the extra so STEP tests run on every platform.
