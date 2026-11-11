# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow the project
phases (`v0.<phase>.0`) until 1.0.

## [Unreleased]

### Changed
- Tiles go face by face (issue #44, product owner 2026-11-11): a flat face gets tiles only if at
  least 85 % of its open top can be tiled, otherwise all of it keeps its studs instead of looking
  patchy (castle tower rims, Duo's base edge). New setting `parts.tiles_min_share` (default 0.85;
  0 = as in 1.7.0); the run says how many faces kept their studs. Tiles are still off by default.

## [1.7.0] - 2026-11-10 - Tiles on flat tops (opt-in)

The first 2.0 item (issue #42, ROADMAP item 9, ADR 0020): with `tile` in `parts.categories`, open
tops that the 3D model has flat (a box's top, a base, a flat detail) get smooth tiles, and the tile
lies where the model's face is, to the plate. The stairs of rounded shapes keep their studs. On the
fixtures the cubes, the L-bracket and the two bodies now match their mesh exactly (surface
deviation 0.83 / 4.05 mm → 0.00 / 0.00 mm, mean / 95th percentile), for 7–16 % more parts; every
fixture stays one stable piece (docs/benchmarks.md, "Tiles (ROADMAP 9)"). Tiles stay off by default
(product owner, 2026-11-11: on the castle the result looks patchy, tower rims and parts of faces keep
their studs); a rule that tiles a face only when at least 85 % of it can be tiled comes next (issue
#44), and with it tiles on by default and 2.0.0.

### Added
- Flat tops from the mesh (`voxel/flat.py`): the voxelizer marks top cells whose top face is level
  and planar in the input mesh (every ray of the cell, at most 1° tilt, heights within 0.1 mm;
  faces of at least 2 cells, plus border cells at least half covered), with the face's height.
  Stored in `VoxelGrid.flat` and in `.npz` (older files still load; voxel files count every top).
- Tile pass after placement (`apply_tiles` in the legolization backend, `place/tiles.py`): a plate
  becomes a tile of its size (part count unchanged), a brick two plates plus tiles; where the face
  is a plate lower a brick becomes one plate plus tiles, where it is a plate higher tiles are laid on
  the part. All nine tile sizes of legolization's catalogue are used (five of them are import-only
  there); 2 × 3 and 2 × 8 tops get two tiles. Only parts the whitelist allows and LEGO makes in the
  colour. When a part got heavier, the whole model is checked again while the steps are planned, and
  the tiles are undone if it would no longer hold together.
- Settings `parts.tiles: flat | all` (`all`: every open top, the stairs too) and
  `parts.tiles_on_base` (tiles on the lowest brick layer, default yes).
- `scripts/compare_previews.py`: two release runs side by side (pictures with parts, tiles,
  deviation). `scripts/benchmark_release.py` records each run's notes.
- Shape fidelity metric for the 2.0 series (`mesh2brick.fidelity`, issue #42): the distance of the
  brick model's outer surface (studs included) to the input mesh, area-weighted mean and 95th
  percentile in mm and studs. `scripts/benchmark_fidelity.py` measures finished release runs,
  `scripts/benchmark_release.py` records it per run (column "Deviation mm"); the 1.6 baseline is in
  docs/benchmarks.md, "Shape fidelity baseline".

### Changed
- legolization's own tile pass is never used (it tiled every open plate, stairs included, never
  bricks, and only in four sizes); `tile` in `parts.categories` now means mesh2brick's pass.
- The five import-only tiles of legolization's catalogue (1 × 3, 1 × 6, 1 × 8, 2 × 4, 2 × 6) count as
  tiles: `catalog list --category tile` shows nine, whitelists apply to them, the PDF names them
  "Fliese" / Tile.
- The LLM layer's prompt says what a tile is (no studs, laid on last).

### Fixed
- `convert` with `llm.enabled` but no API credentials stopped with the SDK's `TypeError`; it now
  skips the LLM layer with the note "no API credentials: set ANTHROPIC_API_KEY".

## [1.6.1] - 2026-11-10 - Rating scale documented

`mesh2brick feedback --help`, README.md and README.de.md state the rating scale: 1 to 5 stars,
5 = best (1 = unusable, 3 = okay); runs rated 4 or 5 become examples for later runs (issue #29,
ROADMAP item 6, the last 1.x item).

### Changed
- `feedback --rate` and the `feedback` command help name the scale; a test checks it independent of
  the terminal width.
- Tests: the LLM pipeline test places the model once and reuses it, so a time cap that fires while
  the laptop sleeps cannot make it fail (issue #30).

## [1.6.0] - 2026-11-10 - Better part estimate in inspect

The part estimate of `inspect` (and of the start of `convert`) retraces what legolization does
(issue #28, ROADMAP item 5, ADR 0019): it hollows and tiles at plate resolution like legolization and
adds what legolization's joining step costs where bricks cannot hold each other: areas one cell high
(castle courtyard, Duo's base) and thin, wide floors. All 15 release runs are inside the shown range
(1.5: 14), the range is on average a factor 1.78 wide instead of 2.22, and the castle is estimated at
1,718 (1,384–2,242) instead of 602 (417–926) for 1,657 placed parts (docs/benchmarks.md, "Part
estimate"). No change to placement, steps or PDF.

### Added
- `PartsEstimate` (low, expected, high, plus the tiled parts and the cells legolization rebuilds) and
  `plate_shell` (legolization's hollowing at plate resolution; a test compares both).
- `scripts/benchmark_estimate.py`: the estimate against a finished release run, without converting.
- `scripts/benchmark_release.py` shows estimate and "in range" per input and how many are inside.

### Changed
- `parts_estimate` takes the voxel grid (colours, cell height) and `hollow` / `wall_thickness`
  instead of the occupancy alone; fixed factors 0.9 / 1.3 / 2.0 are gone.
- The time advice from 2,000 expected parts now appears for Duo at 48 studs only among the test
  models; the STEP cube and the textured cube (about 250 s) no longer get it.
- Fallback for very big models: above 500,000 plate cells of the shell (was: 400,000 cells of the
  solid grid), from the shell size; a sphere of 128 studs is still estimated exactly (1.3 s).

## [1.5.0] - 2026-11-09 - Smaller PDFs for big models

Every booklet of the fixtures is below 10 MB (issue #27, ROADMAP item 4, ADR 0018): textured cube
23.2 → 9.6 MB, STEP cube 20.4 → 6.4 MB, castle 19.4 → 5.1 MB, sphere 10.1 → 4.4 MB. Almost all of a
big booklet were step pictures; for models above 500 parts the parts built earlier are now drawn
without joints (studs stay), with a fast-octree palette at 110 dpi, which also makes the new parts
stand out and the booklet faster to write (textured cube 54 → 31 s). Small models keep the pictures
of 1.4 pixel for pixel (docs/benchmarks.md, "PDF size").

### Added
- `PdfOptions.compact` (default: by model size, above 500 parts) and `PreviewOptions.faded_edges` /
  `octree_palette` for compact step pictures.
- `scripts/benchmark_pdf.py`: where the bytes of a booklet are (step pictures, part tiles, callouts,
  cover, rest), per step picture with covered area and part counts.
- `scripts/benchmark_release.py` reports kB per step and warns above 40 kB for models above 500
  parts.
- pypdf (BSD-3-Clause) as a development dependency: tests read the booklets back.

### Changed
- Step pictures of models above 500 parts: faded parts without joints, octree palette, 110 dpi
  (product owner, 2026-11-09). Part tiles, callouts, cover and text are unchanged.

## [1.4.0] - 2026-11-08 - Stability checks for big models

Big models get stability-checked steps (issue #26, ROADMAP item 3, ADR 0017). They keep the
layer order of 1.3 with parts under overhangs pre-assembled, and every intermediate state is now
checked with legolization's stability model, in parallel on several cores. On every fixture above
500 parts no checked step needs a supporting hand (legolization's own search, still used up to 500 parts,
needs one in 40–75 % of the steps of the hollow organic ones and would take 6–17 minutes there). When the
time limit stops the checks, the states checked by then keep their verdict and the cover says how
many (docs/benchmarks.md, "Scalable stability checks").

### Added
- `steps.sequencing: checked-layers`: layer order with pre-assemblies, every intermediate state
  checked (`backends/checks.py`): one worker walks bottom-up with a warm LP, the others check
  top-down, each state with its own LP; all cores but one, at most 12 processes.
- Cover sentence and command-line note for partly checked plans ("There was time to check k of n
  intermediate states (all of the bottom L of A layers)"); the LLM layer's model description says
  the same.
- `scripts/benchmark_sequencing.py` (step planner alone on finished layouts, with LP counts) and
  `scripts/sequencing_prototypes.py` (the options measured for ADR 0017); `scripts/benchmark_release.py`
  reports checked states and steps that need a hand.

### Changed
- `steps.sequencing: auto` no longer switches to unchecked layer order above 500 parts: it uses
  legolization's search up to 500 parts when its estimated time fits 75 % of the time left
  (`steps/budget.py`), and checked layers otherwise; a search that does not finish in time falls
  back to checked layers instead of unchecked ones. `layers` stays the unchecked layer order.
- With the LLM layer on, the step checks leave 60 s for it.
- Local patch #2: inside the step-check workers only, LPs above 10,000 rows (about 460 parts) skip
  the simplex attempts (they never finished there within 3 s).

### Known
- Within the 5-minute default every state is checked up to about 1,250 parts (Duo at 32 studs:
  all 153 in 139 s); the biggest fixtures get 46–87 % (sphere, vertex-colour model, castle, cubes)
  and the cover says how many. Duo at 48 studs with `--time 20min` gets 217 of 324 (placement alone
  takes half of the 20 minutes); more time checks all.
- A conversion of a big model now uses several cores for up to a few minutes.

## [1.3.0] - 2026-11-07 - Solver order and slopes back on

Slopes are back, and big models convert faster (issue #34, ROADMAP item 8 moved up, ADR 0016).
The stability LPs now try simplex for 3 s and then the interior-point method without crossover.
Small models take the same time as in 1.2, big ones up to 32 s less; with slopes every fixture
stays one stable piece at most 1.45x slower (docs/benchmarks.md, "Solver order and slopes back on").

### Added
- Slopes are drawn as slopes in previews, step pictures and part tiles: the stud row as cells
  with studs, the sloped columns as a wedge down to a half-plate lip, as in LDraw's 3039, 3040b
  and 4286. `PlacedPart.studs` records the stud row (brick-model schema 5).
- `scripts/benchmark_release.py --set KEY=VALUE` applies a setting to every input.

### Changed
- `parts.categories` defaults to `[brick, plate, slope]` again (opt-in since Phase 1);
  `[brick, plate]` turns slopes off.
- Local patch #2: stability LPs try simplex (3 s), the interior-point method without crossover
  (300 s), simplex without presolve (5 s), then legolization's last attempt, in both LP paths
  (also legolization's step planning).

### Known
- legolization's `preserve` mode places few slopes, and most on the inner wall of hollow shells
  (10 of 130 visible on the fixtures). More visible slopes are the 2.0 part of ROADMAP item 8.

## [1.2.0] - 2026-11-07 - Roadmap 2: hard time limit

A conversion no longer runs past `placement.time_limit_s`. Duo at 48 studs (local model) with
a 20-minute limit is one stable piece of 2,308 parts after 733 s (1.0: stopped after more than
an hour); with the default 5 minutes it is cut short after 289 s and marked. Every fixture
gives the parts of 1.0, stays stable and converts up to 48 s faster (docs/benchmarks.md,
"Hard time limit").

### Added
- Roadmap 2 ([#25](https://github.com/leckermatz79/mesh2brick/issues/25)): `placement.time_limit_s`
  is a **hard limit** for the whole conversion (ADR 0015). legolization runs in a child
  process that reports every intermediate layout; at the limit (minus the time kept for the
  export) it is stopped and the best state is used: checked and stable before checked before
  not checked, the latest on ties. The command line names the stage and part count.
- A model cut short is marked `best_so_far` (brick-model schema 4); the PDF cover says "time
  limit reached: the best stable model found by then", or "the last intermediate result"
  when no stable state existed.
- `buildable: not checked` in the command-line summary when the limit stopped the stability
  check (`StabilityReport.checked`).
- `convert --time 20min` (also `90s`, `1h`) sets the time limit; like `--size` it overrides
  `--config` and `--set`.
- `inspect` and the start of `convert` print "expected about 3,905 parts; recommended:
  --time 20min" when the rough estimate is above 2,000 parts and the limit is below 20
  minutes. The limit itself never grows by itself (product-owner decision).
- Up to three parts that nothing holds after placement are removed and the stability is
  checked again, with a note naming the parts; more stay (the model is reported as not
  buildable, as before).

### Changed
- A finished run whose last passes left the model unstable now keeps the stable state before
  them, with a note.
- Local patch #2: large stability LPs get the interior-point method without crossover before
  legolization's last attempt. Duo at 48 studs: the first stability check takes 49 s instead
  of more than an hour.
- The LLM layer is skipped (with a note) when less than 30 s remain before the export.
- An already expired time limit before placement is an error with a clear message instead of
  an unbounded placement.

### Fixed
- Voxelization removes cells no part can hold (no straight brick or plate through them
  reaches a cell with something above or below), with a note. Duo at
  48 studs had one such cell, which always became a loose 1 x 2 brick. No fixture has any.

## [1.1.0] - 2026-11-07 - Roadmap 1: size in centimetres

### Added
- Roadmap 1 ([#24](https://github.com/leckermatz79/mesh2brick/issues/24)): the size of the
  LEGO model in centimetres. `input.target_height_cm` sets the height (a size in cm means the
  height, by product-owner decision); it replaces `input.target_studs` and is rounded to the
  nearest whole brick or plate, so 30 cm become 31 bricks = 29.8 cm.
- `--size` for `convert`, `voxelize` and `inspect`: `30cm` or `300mm` (height) or `40studs`
  (longest edge, as `input.target_studs`). It overrides the size settings of `--config` and
  `--set`, also `scale_mode: mm`.
- `inspect` and `voxelize` name what sets the size: `(height 30 cm -> 31 bricks)` or
  `(longest axis -> 32 studs)`.

### Changed
- Messages for models that are too small suggest `--size` instead of `input.target_studs`.

## [1.0.0] - 2026-11-07 - Phase 8: Blender, inspect, v1.0

First complete release: every phase of the plan is done and the v1.0 Definition of Done
(SPEC §9) is met: a STEP model with `--config` gives `.mpd`, three parts lists and a PDF in
under 5 minutes for up to 2,000 parts, every fixture is one stable piece, coverage 96 %
(docs/benchmarks.md, "v1.0 acceptance").

### Added
- `.blend` import (ADR 0014): mesh2brick runs the user's Blender headless (factory settings,
  auto-run scripts disabled) and reads the visible objects of the active scene with modifiers
  applied, curves and text as meshes, material and vertex colours, in the scene's units.
  Blender is found via `MESH2BRICK_BLENDER`, `PATH` or the usual install locations.
- glTF input (`.glb`, `.gltf`) with the spec's conventions: Y up, metres, linear colours,
  `baseColorFactor` × `COLOR_0`.
- `mesh2brick inspect`: size in the file and in LEGO, colour sources and the LEGO colours
  they become, warnings and a rough part count in seconds (no placement), plus
  `<name>.inspect.png` with the model as read next to its voxels. Replaces the placeholder.
- `render/mesh.py`: a small numpy z-buffer rasteriser for mesh pictures (exact where parts
  interpenetrate; 2 million triangles in a few seconds).
- `tests/fixtures/rocket.blend` (CC0, built by `scripts/make_blend_fixture.py`).
- `scripts/benchmark_release.py` (v1.0 acceptance, SPEC §9) and `scripts/make_gallery.py`
  (example gallery in `docs/gallery/README.md`).
- The PDF cover lists the build sections with their pages (product-owner decision of
  2026-11-07); booklets without sections look as before.

### Fixed
- 16-bit vertex colours in glTF (Blender's default) were wrapped modulo 256 by trimesh;
  they are rescaled before trimesh builds the meshes (UPSTREAM #14).

### Changed
- Version 1.0.0; development status "Production/Stable". Public CLI flags and settings now
  follow semantic versioning.

### Removed
- The "planned for Phase N" placeholder and its exit code 3: every command works now.

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
