# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow the project
phases (`v0.<phase>.0`) until 1.0.

## [Unreleased]

### Added
- The PDF cover lists the build sections with their pages (product-owner decision of
  2026-11-07); booklets without sections look as before.

## [0.7.0] - 2026-11-07 - Phase 7: LLM layer

### Added
- Optional LLM layer (`mesh2brick.agent`, extra `llm`, ADR 0013): with `llm.enabled`,
  Claude names build sections, may merge runs of consecutive steps, and writes one short
  sentence per step in the booklet language. mesh2brick checks every proposal against the
  model (merges keep every part held and visible and hide no moment that needs a hand;
  texts mention only parts and quantities of their own step) and falls back to the result
  without the layer for anything that fails, for refusals, API errors and the cost limit.
- Tools Claude may call: `catalog_lookup`, `stability_check`, `render_preview`.
- `choose_part` (opt-in, with `parts.availability: report`): picks a replacement among
  catalogue-checked options for parts LEGO does not make in their colour; the PDF's parts
  notes show it.
- `<name>.llm.json`: tasks, accepted output, tokens and cost of every run.
- Local feedback store (SQLite) and `mesh2brick feedback`: list runs, `--rate 1-5 --note`,
  `--export` as JSON lines; runs rated 4–5 become few-shot examples, notes are passed on.
- New settings `llm.effort`, `llm.max_cost_usd`, `llm.max_turns`, `llm.examples`,
  `llm.feedback`.
- German booklets show a German colour name in brackets ("Bright Green (Hellgrün)").
- `BrickModel` schema 3: per-step `section` and `text`; the PDF shows both.
- `steps/regroup.py` (merge runs of steps safely) and `merge_steps` in the backend.
- `scripts/benchmark_llm.py`; real models cost $0.06–0.20 per run (docs/benchmarks.md).

### Fixed
- Step numbers with three digits no longer overlap the parts call-out.
- `docs/THIRD_PARTY.md` listed the Anthropic SDK as MIT; it is Apache-2.0.

## [0.6.0] - 2026-11-07 - Phase 6: instruction quality

### Added
- Own PDF instructions (`mesh2brick.render.pdf`, ADR 0011) in German or English: cover with
  a picture of the model, part and step count, size in cm, weight, colours and a plain
  stability verdict; parts-list pages with one picture per part and colour (common scale),
  quantity, name and LDraw number; step pages with part call-outs, faded earlier parts,
  sub-assemblies on tinted panels, an attach call-out, "put together first" views from
  below, and hints in plain words. DejaVu Sans is embedded; step pictures are embedded as
  palette PNGs without re-encoding.
- `output.steps_per_page` (1–4, default 2); `output.language` now applies to the PDF.
- Own step passes (`mesh2brick.steps`, ADR 0012): parts that would hang in the air in
  layer-order steps move into the step of the part holding them (pre-assembly units);
  steps below half of `steps.parts_per_step` are merged into a neighbour, oversized
  layer-order steps are split. Real test model: hanging parts 155 → 0, steps with fewer than
  3 parts 11 → 4.
- `BrickModel` schema 2: per-step `stable`/`fragile`, per-part `unit`, `mass_g`,
  `buildable`, `size_mm()`; schema 1 files still load.
- Step pictures grow with the model instead of always showing the finished model's frame.
- `scripts/benchmark_instructions.py` (step sizes, hanging parts, PDF size and time).

### Changed
- Default `output.formats` writes `.mpd` instead of `.ldr`, so sub-assemblies stay LDraw
  sub-models with their own steps (`ldr` is still available).
- `reportlab` is now a direct dependency (it was already installed through legolization).

### Removed
- `LegolizationBackend.write_instructions` (legolization's booklet).

## [0.5.0] - 2026-11-01 - Phase 5: strategy benchmark and colour availability

### Added
- `parts.availability` (`exclude` default, `split`, `report`) for parts LEGO does not make in
  a colour (ADR 0010). `exclude` leaves them out of placement for the whole model; `split`
  replaces them afterwards by existing shorter parts of the same colour with staggered joints
  (`mesh2brick.place.split`), rolls back failed replacements and re-checks stability.
- Strategy benchmark of all 7 legolization strategies on the fixtures at 16 and 32 studs
  (docs/benchmarks.md, gallery chart); decision "no own strategy" (ADR 0010).
- `scripts/benchmark_placement.py` reports parts not made in their colour, the share of
  stacked vertical joints (`stacked_joints`) and the notes.
- Studio check of the product owner compared with legolization's stability analysis (ADR 0010
  addendum): no minimum wall thickness, no own offset pass; README notes how to open files in
  Studio (File → Open; Import hangs on macOS).

## [0.4.0] - 2026-11-01 - Phase 4: catalogue and whitelist

### Added
- `mesh2brick catalog list [--category] [--all] [--json]` and `catalog show PART`, offline:
  size, studs, BrickLink/Rebrickable numbers, Rebrickable name, colours a part is made in,
  and whether the current `parts.*` settings allow it (ADR 0009).
- `PartSpec` derived from the LDraw geometry through pyldraw3 (footprint, height, top
  studs, category), cached as JSON per LDraw release in the user cache directory; checked
  against legolization's cell model for all 29 placeable parts.
- Whitelist/blacklist: `parts.include` and `parts.exclude` now reach placement (local patch
  of `legolization.pipeline.default_catalog` during `run()`, upstream draft #8). Impossible
  settings fail early with a clear message; the 1 x 1 fillers are added to include lists.
- Parts lists: Rebrickable part names and a `produced_in_color` column; part/colour pairs
  LEGO never produced are reported.
- `id_maps.json` schema 3 (moved to `mesh2brick/catalog/`): Rebrickable names, available
  colours per part (Rebrickable `elements.csv`), renamed colours via ID + RGB and
  Rebrickable's name (LDraw "Medium Lilac" = "Dark Purple"), match provenance.

### Changed
- The `common` palette gains Dark Purple (42 colours).
- Direct dependency: platformdirs.

## [0.3.0] - 2026-11-01 - Phase 3: STEP and colours

### Added
- STEP import (`.step`/`.stp`) through the optional extra `step` (cascadio/OpenCASCADE,
  ADR 0007): assemblies, solids and colours; `input.step_tolerance_mm` (0.05 mm) sets the
  tessellation tolerance in millimetres whatever the file unit is.
- `input.multi_body` (`union`/`error`) for files with several bodies, for every format.
- Colours from the model (ADR 0008): `color.mode` `cad`, `vertex`, `texture` and the new
  default `auto`. Sources: 3MF base materials and colour groups, Bambu Studio/Orca and
  PrusaSlicer filament assignments, STEP colours, OBJ/glTF materials and textures (glTF
  tint in linear light), PLY/OBJ vertex colours. Only the visible outer surface votes
  (rays along x, y and z, union boundary), each cell takes the majority colour, thin
  coatings colour the cell behind them, the rest copies the nearest coloured cell.
- `color.palette` `common` (new default: ~40 colours LEGO currently makes in many parts,
  from Rebrickable's statistics), `solid`, `all`; matching uses legolization's metric.
- 3MF: slicer modifier, negative and support-helper volumes are no longer read as geometry;
  painted colours and 3MF textures are reported as not supported yet.
- Fixtures: `cube_10mm.step`, `two_bodies.step` (own AP214 writer in
  `scripts/make_fixtures.py`), `toadstool.obj`, `vertex_colors.ply`, `textured_cube.obj`.

### Changed
- Mesh parts are merged as plain geometry (colours tracked separately), so UV seams no
  longer keep meshes open; models made of touching closed parts use the exact volume method.
- `id_maps.json` (schema 2): Rebrickable colour numbers also by exact name (90 instead of
  69 colours confirmed), plus Rebrickable usage statistics per colour.
- Optional extra `step`: cascadio replaces the cadquery placeholder.
- CI installs the `step` extra; STEP tests must not skip there.

### Fixed
- ADR 0005 overstated the confirmed colours (93 for BrickLink, not for both catalogues).

## [0.2.0] - 2026-11-01 - Phase 2: end-to-end MVP

### Added
- `mesh2brick convert`: mesh or voxel grid -> LDraw (`.ldr`/`.mpd`), brick model JSON,
  parts lists, PDF instructions and preview, with per-stage timings (`mesh2brick.pipeline`).
- Bills of materials (`mesh2brick.export.bom`): mesh2brick CSV, BrickLink wanted-list XML,
  Rebrickable CSV; LDraw -> BrickLink/Rebrickable numbers from a generated, source-confirmed
  table (`export/id_maps.json`, `scripts/make_id_maps.py`, ADR 0005); unconfirmed lines are
  reported, never guessed.
- PDF instructions via legolization's booklet with mesh2brick step images (new parts
  highlighted, earlier ones faded, subassembly steps framed separately), A4/letter.
- Strict LDraw self-check after export (`verify_ldraw`, legolization's strict importer).
- Time-bounded conversion (ADR 0006): `placement.time_limit_s` (300 s), `steps.sequencing`
  (`auto`/`thorough`/`fast`/`layers`), stability-checked step planning in a child process
  with layer-order fallback, legolization `time_budget_s` defaulting to 25 % of the budget.
- `voxel.min_island_fraction`: loose voxel islands below 5 % are removed (a 2-cell island
  made a real model unbuildable and slow).
- `scripts/benchmark_placement.py` (isolated, time-limited runs with phase logs);
  benchmark rounds 1–3 in `docs/benchmarks.md`.

### Changed
- Default strategy `kollsker` (was `luo`), chosen by benchmark.
- Default output formats include `bom_rebrickable` (Phase 2 needs three BOM formats).
- Preview renderer vectorised with numpy (~8x faster); step images palette-compressed.
- CLI progress thins legolization's per-layer lines to quarters.
- Dependencies: pillow (palette PNGs).

### Upstream
- Filed hbmartin/legolization#88 and draft PR #89 (LP attempt time limit).


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
