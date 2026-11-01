# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow the project
phases (`v0.<phase>.0`) until 1.0.

## [Unreleased]

## [0.1.0] - 2026-11-01 - Phase 1: ingest and voxelization

### Added
- `mesh2brick.ingest`: loader registry by suffix; STL/OBJ/PLY via trimesh; own 3MF reader
  (core spec + production extension, units, nested components, build transforms);
  normalisation (up axis, optional `auto_orient` onto the most stable side, merge vertices,
  drop degenerate faces, fill small holes, outward normals) with per-face part ownership.
- `mesh2brick.voxel.voxelize`: volume-fraction voxelization by column rasterization
  (4 x 4 rays per stud, winding-number union, exact per-cell inside length), brick or plate
  cells, documented rounding rule, surface fallback for open meshes, `hollow()` erosion
  (ADR 0003, ADR 0004).
- `mesh2brick.voxel.color`: modes `single` and `height_bands` (new `color.bands`).
- `mesh2brick.voxel.io`: `.grid.npz` (lossless), legolization-compatible `.npy` and
  MagicaVoxel `.vox`.
- CLI `voxelize` (summary with LEGO size, volume error, shell estimate; `--vox`, `--npy`,
  PNG preview); `place` accepts `.grid.npz`; voxel-grid previews.
- Backend helpers: solid-palette lookup (`color_info`, `color_rgb`) and legolization's mesh
  voxelizer as benchmark reference.
- Fixtures (CC0, `scripts/make_fixtures.py`): cube, sphere, L-bracket, torus, low-poly
  bunny; acceptance tests; `scripts/benchmark_voxelize.py`, `docs/benchmarks.md`.
- Dependency: networkx (trimesh hole filling).

### Changed
- Default `input.target_studs` is now 32 (was 48 per SPEC §4), by product-owner decision.
- Default `parts.categories` is `[brick, plate]`; slopes are opt-in until the legolization
  LP stall is fixed upstream (docs/UPSTREAM.md #2).

### Fixed
- Placement could hang indefinitely: legolization 0.5.0 runs HiGHS without a time limit
  and HiGHS presolve stalls on some stability LPs. Local patch adds a 5 s limit to every
  attempt but the last (both LP paths), with a captured-LP regression test.
- CI jobs have time limits (10/30 min) so a hang fails fast.

## [0.0.0] - 2026-11-01 - Phase 0: skeleton

### Added
- Project skeleton: `uv`, `src/` layout, extras `step`, `blender`, `llm`, dev dependency group;
  ruff, mypy (strict), pytest + coverage, pre-commit, GitHub Actions (Linux/macOS, Python 3.12/3.13).
- Backends pinned exactly: legolization 0.5.0, pyldraw3 1.7.0, rebrickable 1.1.0.
- `mesh2brick.config`: full settings schema (SPEC §4), YAML loader, `--set key=value` overrides,
  readable validation errors; example `examples/mesh2brick.yaml`.
- `mesh2brick.voxel.grid.VoxelGrid`: immutable z-up stud-raster grid (brick or plate cells).
- `mesh2brick.model.BrickModel`: backend-independent, JSON-serialisable placed model with build
  steps and subassembly metadata.
- `mesh2brick.backends`: `Placer`/`StabilityChecker`/`StepSequencer`/`Exporter` protocols and the
  legolization adapter (settings translation, grid conversion, `.ldr`/`.mpd` export); LDraw
  library status via pyldraw3.
- `mesh2brick.render.preview`: painter's-algorithm PNG preview with part outlines, studs and
  per-step rendering.
- CLI: `place` (voxel file → LDraw + brick model + preview) and `render`; `convert`, `voxelize`,
  `catalog`, `inspect`, `feedback` announce their phase.
- Tests: legolization smoke test (heart.vox → .ldr), LDraw coordinate round trip, architecture
  rule (only `backends/` imports LEGO libraries), SPDX headers.
- Docs: README (en/de), CLAUDE.md, ADR 0001/0002, THIRD_PARTY, UPSTREAM, STATUS, PLAN, gallery.
