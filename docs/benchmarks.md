# Benchmarks

Measured on the development laptop (Apple Silicon, macOS, Python 3.12), single process.
Update this file whenever voxelization, the backend configuration or a placement strategy
changes (SPEC §8.6).

## Voxelization (Phase 1, 2026-11-01)

`uv run python scripts/benchmark_voxelize.py --studs 32`. Both voxelizers get the same pitch
(longest axis = 32 studs) and plate-height cells. Δ volume compares filled cells with the mesh
volume. For overlapping parts (bunny) the mesh volume double-counts the overlaps, so a small
negative value there is correct.

| Model | Triangles | Grid (studs x studs x plates) | mesh2brick cells | Δ volume | time | legolization cells | Δ volume | time |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| cube_10mm | 12 | 32 x 32 x 80 | 81,920 | +0.0% | 0.02 s | 88,209 | +7.7% | 0.21 s |
| sphere_r10 | 5,120 | 32 x 32 x 80 | 42,832 | +0.1% | 0.02 s | 47,325 | +10.6% | 0.10 s |
| l_bracket | 20 | 24 x 8 x 80 | 7,680 | +0.0% | 0.00 s | 9,585 | +24.8% | 0.12 s |
| torus | 2,304 | 32 x 32 x 18 | 8,160 | -0.0% | 0.01 s | 10,392 | +27.3% | 0.04 s |
| bunny_lowpoly | 2,880 | 30 x 16 x 79 | 10,870 | -4.2% | 0.01 s | 13,551 | +19.4% | 0.10 s |

A real-world model with 2.1 million triangles in 12 parts (3MF from Bambu Studio, local
test, not in the repository) voxelizes in 0.9 s at 32 studs. Loading the file takes
7–10 s (STL/3MF parsing plus repair).

**Reading:** legolization marks every cell the surface touches, so it systematically adds
a skin (+8 % to +27 %). Volume fractions with a 0.5 threshold match the true volume within
a few tenths of a percent (ADR 0003).

## Placement through legolization 0.5.0 (Phase 1, 2026-11-01)

Default settings (strategy `luo`, hollow, wall 2, slopes `preserve`), 12 studs, brick cells.

| Model | Cells | Parts | Steps | Buildable | Time |
|---|---:|---:|---:|---|---:|
| cube_10mm | 1,440 | 223 | 42 | yes | 11.1 s |
| l_bracket | 144 | 31 | 11 | yes | 0.7 s |
| sphere_r10 | 760 | 203 | 42 | yes | 14.5 s |
| torus | 136 | 125 | 21 | yes | 1.0 s |
| bunny_lowpoly | 186 | 84 | 26 | yes | 1.5 s |
| sphere_r10 (`greedy`) | 760 | 209 | 44 | yes | 17.1 s |
| bunny_lowpoly (`greedy`) | 186 | 124 | 30 | yes | 2.8 s |

80–90 % of the time goes into stability LPs (`stability.analyze`), the rest mostly into
step sequencing. `luo` gives fewer parts than `greedy` at similar speed, so it stays the
default. A full strategy benchmark follows in Phase 5.

## Real-world model at 32 studs (Phase 2, 2026-11-01)

Local test model (owl figure from a 3MF slicer project, not in the repository): 32 x 19
studs x 24 bricks, 4,507 cells, hollow shell of ~2,400 cells (wall 2), roughly 1,100 parts.
Target (product owner): complete `convert` in **under 5 minutes**.
`scripts/benchmark_placement.py`, each run in its own process, hard limit 600 s, 8–10 runs in
parallel on a 12-core laptop. `bN` = legolization `time_budget_s=N` (bounds placement and
repair only).

**Round 1:** grid still had a 2-cell loose island (wall 2, `b120`).

| Strategy | Result | Total | place | repair | remerge | sequencing | Parts | Buildable |
|---|---|---:|---:|---:|---:|---:|---:|---|
| kollsker | ok | 235 s | 6 s | 99 s | 74 s | 30 s | 1,083 | no (2 pieces) |
| smga | ok | 242 s | 78 s | 30 s | 103 s | 2 s | 1,128 | no |
| beauty | ok | 248 s | 79 s | 31 s | 106 s | 2 s | 1,219 | no |
| bond | ok | 356 s | 6 s | 115 s | 65 s | 146 s | 1,051 | no |
| fast | ok | 569 s | 5 s | 109 s | 102 s | 326 s | 1,104 | no |
| luo / luo solid / greedy | > 600 s | – | 133–146 s | – | 145–149 s | stuck | – | – |

**Finding:** the loose 2-cell island made every result non-buildable and triggered the repair
search. This led to `voxel.min_island_fraction` (islands below 5 % are removed).

**Round 2:** island removed (wall 2, `b60`, `b30`). No repair phase was needed any more. The
model is now stable as placed.

| Strategy | Result | Total | place | remerge | sequencing | Parts | Buildable |
|---|---|---:|---:|---:|---:|---:|---|
| kollsker b30 | ok | 539 s | 8 s | 103 s | 398 s | 1,080 | **yes** |
| all others (luo, greedy, bond, fast, smga, beauty, kollsker b60) | > 600 s | – | 4–50 s | 59–169 s | stuck | – | – |

**Finding:** step sequencing (legolization checks the stability of every intermediate state
and searches when it gets stuck) is now the bottleneck, followed by the final remerge. Neither
phase is bounded by `time_budget_s`. That led to `steps.sequencing` (thorough / fast / layers).

**Round 3:** sequencing modes and wall thickness (`b60`, island removed).

| Strategy | Wall | Sequencing | Result | Total | place | remerge | sequencing | Parts | Buildable |
|---|---:|---|---|---:|---:|---:|---:|---:|---|
| kollsker | 2 | layers | ok | **88 s** | 6 s | 55 s | ~0 s | 1,077 | **yes** |
| kollsker | 1 | layers | ok | 90 s | 9 s | 40 s | ~0 s | 1,566 | yes |
| greedy | 1 | layers | ok | 191 s | 43 s | 112 s | ~0 s | 1,507 | yes |
| kollsker | 2 | fast | ok | 338 s | 6 s | 55 s | 250 s | 1,077 | yes |
| kollsker | 1 | thorough / fast | > 600 s | – | 10 s | 40 s | stuck | – | – |
| luo, bond | 1 | fast | > 600 s | – | 8–40 s | 34–111 s | stuck | – | – |

**Findings and decision (ADR 0006):**

- **Wall thickness 1 is not a lever:** thinner shells need *more*, smaller parts (1,566 vs 1,077),
  so the default stays at 2.
- **kollsker** places in seconds and keeps the part count low, so it becomes the default
  strategy (SPEC had `luo`).
- **Stability-checked sequencing** scales steeply with model size (11 s at 226 parts,
  ~400 s at ~1,080 parts). Up to 500 parts it is used. Above that, or when the 5-minute
  budget runs out, steps follow layer order (`steps.sequencing: auto`).

## Colours from the model (Phase 3, 2026-11-01)

Default settings (32 studs, `color.mode: auto`, `color.palette: common`), `mesh2brick
convert`, two runs in parallel on the development laptop.

| Model | Colour source | Colours | Parts | Steps | Buildable | Total | voxelize (incl. load) | place | PDF |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| owl figure, 3MF (local) | Bambu Studio filaments, 12 parts | 5 | 1,013 | 158 | yes | 137 s | 13 s | 104 s | 20 s |
| owl figure, single colour (Phase 2) | – | 1 | 1,077 | 171 | yes | 110 s | 11 s | 78 s | 21 s |
| `toadstool.obj` | OBJ materials, overlapping parts | 2 | 1,240 | 184 | yes | 179 s | 0.4 s | 149 s | 30 s |

The colour transfer itself (rays along three axes, vote, fill) adds about 0.6 s on the
2.1-million-triangle owl; loading the 3MF stays at ~11 s. Colour boundaries did not raise the
part count: the coloured owl came out with 6 % fewer parts than in one colour (the colour
boundaries change where legolization splits and merges bricks; not investigated further).
Both models stay well inside the 5-minute budget.

## Whitelists (Phase 4, 2026-11-01)

`bunny_lowpoly.stl` at 20 studs, defaults otherwise (`kollsker`), one run each:

| Parts allowed | Parts | Steps | Time |
|---|---:|---:|---:|
| all 22 bricks and plates | 177 | 41 | 5 s |
| `parts.include=[3001, 3003, 3004]` (+ 3005, 3024 added automatically) | 356 | 58 | 85 s |

Narrow whitelists double the part count here and make placement much slower. The cause was
not investigated further; the time for single-part exclusions was not measured.

## Strategies on the fixtures (Phase 5, 2026-11-01)

`scripts/benchmark_placement.py`, every run in its own process, six in parallel on the
12-core laptop, `steps.sequencing=layers` (so the numbers measure placement, not step
planning), defaults otherwise (hollow, wall 2, brick height, bricks and plates). Cells show
parts / wall time; **bold** = fewest parts for that model. Every completed run was
buildable (stable, one piece).

**16 studs** (time limit 300 s):

| Model | greedy | luo | bond | fast | smga | beauty | kollsker |
|---|---:|---:|---:|---:|---:|---:|---:|
| `cube_10mm` | 180 / 10 s | 737 / 63 s | 209 / 7 s | 168 / 8 s | 256 / 48 s | 138 / 29 s | **136** / 5 s |
| `sphere_r10` | 979 / 79 s | 399 / 70 s | 312 / 12 s | 355 / 17 s | 316 / 63 s | 303 / 55 s | **268** / 4 s |
| `l_bracket` | 38 / 2 s | 59 / 2 s | 39 / 2 s | **32** / 2 s | 36 / 12 s | 36 / 3 s | **32** / 2 s |
| `torus` | 143 / 2 s | 297 / 3 s | 214 / 3 s | 288 / 3 s | **69** / 13 s | 293 / 17 s | 213 / 3 s |
| `bunny_lowpoly` | 126 / 4 s | 226 / 4 s | 114 / 3 s | 101 / 3 s | 247 / 18 s | 78 / 11 s | **74** / 2 s |
| `toadstool` | 571 / 14 s | 569 / 73 s | 261 / 9 s | 289 / 6 s | **255** / 42 s | 256 / 46 s | 374 / 9 s |

**32 studs** (time limit 420 s):

| Model | greedy | luo | bond | fast | smga | beauty | kollsker |
|---|---:|---:|---:|---:|---:|---:|---:|
| `sphere_r10` | > 420 s | > 420 s | 1,849 / 263 s | 2,035 / 167 s | > 420 s | > 420 s | **1,499** / 84 s |
| `bunny_lowpoly` | 1,828 / 196 s | 1,502 / 170 s | 816 / 82 s | 790 / 64 s | 954 / 210 s | **722** / 166 s | 873 / 89 s |
| `toadstool` | > 420 s | > 420 s | 1,465 / 180 s | 1,554 / 180 s | 1,602 / 333 s | > 420 s | **1,224** / 152 s |

**Reading:**

- No strategy wins everywhere. `kollsker` has the fewest parts on 4 of 6 models at 16 studs
  (one of them a tie with `fast`) and on 2 of 3 at 32 studs. It is the fastest or close to
  it everywhere. Only `kollsker`, `bond` and `fast` finished every model within the limit,
  and of those `kollsker` needed the fewest parts except on the 32-stud bunny and the
  16-stud toadstool.
- Where others win, they win at a price:
  - `smga` builds the torus with a third of the parts (69 vs 213) and the toadstool at
    16 studs with 255 vs 374, but it is 4-5x slower and times out on the 32-stud sphere.
  - `beauty` saves 17 % on the bunny at 32 studs (722 vs 873) in twice the time and times
    out on the other two.
- `greedy` and `luo` are never the best and time out on the larger models.

Decision (ADR 0010): `kollsker` stays the default, and no own strategy. Choosing among the
existing strategies per model (e.g. "try `smga` when there is time left") is possible later
without new placement code.

## Parts LEGO does not make in a colour (Phase 5, 2026-11-01)

Real model (owl figure, local, 32 studs, `kollsker`, layer steps), the three
`parts.availability` modes, one run each, three in parallel:

| Mode | Parts | Steps | Stable, one piece | Not made in that colour | Time |
|---|---:|---:|---|---:|---:|
| `report` (flag only) | 1,013 | 158 | yes | 36 | 106 s |
| `split` (shorter bricks afterwards) | 1,049 | 165 | yes | 0 | 130 s |
| `exclude` (leave out beforehand) | 1,025 | 164 | yes | 0 | 70 s |

The model needs 20 bricks 2 x 8 and 16 bricks 1 x 8 in Bright Green, which LEGO does not
make (Rebrickable elements).

- `split` replaces those 36 bricks by 72 shorter ones (2 x 4, 1 x 4, joints staggered
  against the layers above and below) and takes 23 s longer than `report` (it includes a
  second stability check; the split of that time was not measured).
- `exclude` leaves 3007 and 3008 out of placement for the whole model. legolization then
  plans with the shorter bricks from the start: 12 more parts instead of 36, and the final
  merge took 40 instead of 74 s.

`exclude` becomes the default. The more precise "per colour" restriction needs legolization
to accept allowed parts per colour (follow-up to upstream #8).

## Studio check against legolization (Phase 5, 2026-11-01)

The product owner opened the owl's `.ldr` (32 studs, `kollsker`, 1,013 parts) in BrickLink
Studio:

- 0 overlaps, 0 duplicates, 0 stability issues.
- 31 "clutch power" hints (12 warnings, 19 cautions), concentrated on one wing and the feet.

The same file through legolization's analysis and graph checks (`layout_from_ldraw`, then
`analyze`):

| Check | Result |
|---|---|
| legolization stability | stable; highest load 0.020 of a stud's clutch capacity |
| Where the highest loads are | wing tip (x 1–2, layer 42: 0.020) and the legs above the feet (0.006–0.015) – the regions Studio marks |
| Groups hanging on one connection (bridge in the stud graph) | none holding 3 or more bricks; largest group behind a single brick: 3 bricks |
| Wing thickness | mostly 2–3 studs; 1-stud cross-sections: 10 % (left), 7 % (right); bricks in 1-stud walls: 25 of 1,013 |
| Vertical joints continuing straight through a brick interface | 41 % (834 of 2,032) |

Both tools agree there is no stability problem. Studio's clutch hints are about robustness
when the model is handled (pulling, pushing); legolization only checks gravity. Its most
loaded bricks are in the same places, at 2 % of capacity.

Levers tried against the stacked joints (owl, layer steps):

| Variant | Parts | Stacked joints | Time |
|---|---:|---:|---:|
| `kollsker` (default) | 1,013–1,025 | 41–43 % | 70–104 s |
| `bond` strategy | 1,208 | 47 % | 118 s |
| `kollsker`, stretcher-bond penalty ×3 / ×10 (`bond_alpha1` 12 / 40) | 1,013 | 41 % | 104 s |
| `kollsker`, `refine=False` | 1,013 | 41 % | 104 s |
| own post-pass: re-cut rows of equal bricks with staggered joints | 1,013 | 41 % (834 → 824) | < 1 s |

None of them helps:

- The bond weight and `refine` do not change `kollsker`'s layout at all.
- `bond` needs 18 % more parts.
- The own post-pass finds only 10 rows to re-cut, because stacked joints mostly sit where
  bricks of different width or height meet. The pass was removed again; the joint metric
  stays (`stacked_joints`, reported by `scripts/benchmark_placement.py`).

Decision (ADR 0010, addendum): no minimum wall thickness and no own offset pass. Bond-aware
placement is an upstream topic (candidate #11).

## Instructions (Phase 6, 2026-11-07)

`uv run python scripts/benchmark_instructions.py MODEL@STUDS ... --jobs 4`, default settings
(`kollsker`, hollow, wall 2, 2 steps per page, German). Four runs in parallel, so the
placement times are a little slower than in a single run. "Before" is the step plan as
legolization made it, "after" is the plan after mesh2brick's own step passes (ADR 0012).
Models above 500 parts get layer-order steps without stability checks ("Steps checked: no").
The real test model (owl, 3MF) is local only, not in the repository.

| Model @ studs | Parts | Steps checked | Sub-assemblies | Steps | Parts per step (min / median / max) | Steps < 3 parts | Hanging parts | Pre-assemblies | PDF pages | PDF size | PDF time | Placement |
|---|---:|---|---:|---|---|---|---|---:|---:|---:|---:|---:|
| cube_10mm @ 16 | 136 | yes | 1 | 21 → 20 | 2 / 8 / 9 → 2 / 8 / 9 | 2 → 1 | 0 → 0 | 0 | 12 | 1.1 MB | 2 s | 7 s |
| sphere_r10 @ 16 | 268 | yes | 4 | 49 → 49 | 1 / 7 / 9 → 1 / 7 / 9 | 4 → 4 | 22 → 22 | 0 | 27 | 1.9 MB | 4 s | 13 s |
| l_bracket @ 16 | 32 | yes | 1 | 14 → 14 | 2 / 2 / 4 → 2 / 2 / 4 | 10 → 10 | 0 → 0 | 0 | 9 | 0.5 MB | 1 s | 2 s |
| torus @ 16 | 213 | yes | 5 | 47 → 41 | 1 / 6 / 8 → 1 / 7 / 10 | 7 → 6 | 0 → 0 | 0 | 23 | 1.6 MB | 3 s | 5 s |
| bunny_lowpoly @ 16 | 74 | yes | 3 | 25 → 20 | 1 / 3 / 10 → 1 / 3 / 10 | 10 → 3 | 2 → 2 | 0 | 12 | 0.8 MB | 1 s | 3 s |
| toadstool @ 16 | 374 | yes | 1 | 59 → 55 | 1 / 7 / 9 → 4 / 7 / 10 | 1 → 0 | 0 → 0 | 0 | 31 | 2.3 MB | 4 s | 18 s |
| **bunny_lowpoly @ 32** | 873 | no | 0 | 131 → 125 | 2 / 7 / 9 → 4 / 7 / 14 | 1 → 0 | 138 → 0 | 88 | 65 | **5.5 MB** | 16 s | 85 s |
| sphere_r10 @ 32 | 1,499 | no | 0 | 219 → 207 | 2 / 7 / 9 → 1 / 7 / 18 | 2 → 2 | 374 → 0 | 250 | 106 | 10.1 MB | 42 s | 72 s |
| torus @ 32 | 552 | no | 0 | 81 → 74 | 3 / 7 / 9 → 2 / 7 / 13 | 0 → 1 | 94 → 0 | 43 | 39 | 4.1 MB | 9 s | 6 s |
| owl (local) @ 32 | 1,025 | no | 0 | 164 → 153 | 1 / 7 / 9 → 1 / 7 / 10 | 11 → 4 | 155 → 0 | 105 | 81 | 7.0 MB | 21 s | 80 s |

The whole `convert` of the owl takes 99 s (voxelize 11 s, place 67 s, PDF 20 s).

**Reading:**

- **Hanging parts** (a part with no connection to the table when its step is done) are a
  layer-order problem: 94–374 per large model before, none after. Each becomes part of a
  pre-assembly with the part that holds it; none of them was blocked from above. Checked
  plans keep legolization's own order; their few hanging parts (sphere and bunny at 16
  studs) are steps legolization marks as "needs a supporting hand", and the PDF says so.
- **Small steps** drop where a neighbour has room and nothing gets covered (owl 11 → 4,
  bunny @ 16 10 → 3). They stay where the next layer would hide them: the L-bracket is a
  2-stud tower that grows by one layer of two parts per step, and the owl's remaining
  ones are large plates covered by the next step.
- **Large steps:** pre-assemblies that touch each other cannot be cut apart, so single
  layer-order steps reach 13–18 parts (sphere @ 32: one step of 18; usually 10 at most).
- **PDF size:** 6–7 kB per part on large models; the bunny stays well below the 10 MB
  target. The step pictures are palette PNGs embedded unchanged; reportlab's own embedding
  doubled the size in a test (82 instead of 38 kB per picture).

## LLM layer (Phase 7, 2026-11-07)

`uv run python scripts/benchmark_llm.py tests/fixtures/toadstool.obj@16
tests/fixtures/sphere_r10.stl@16 tests/fixtures/bunny_lowpoly.stl@32:en` against the
Anthropic API with the defaults (`claude-sonnet-5-5`, effort `medium`, tasks
`group_steps` and `write_step_text`). The real test model (Duo, 3MF, 32 studs) ran locally
with the same script; it is not in the repository. "Input tokens" counts all input,
"cached" the part read from the prompt cache (a tenth of the price).

| Model | Lang | Parts | Steps | Merges | Sections | Step texts accepted | Requests | Input tokens (cached) | Output tokens | Cost | LLM time |
|---|---|---|---|---|---|---|---|---|---|---|---|
| toadstool-16 | de | 374 | 55 | 0 | 6 | 55 of 55 | 4 | 39,035 (28,691) | 2,897 | $0.061 | 21 s |
| sphere_r10-16 | de | 268 | 48 → 47 | 1 | 8 | 48 of 48 | 4 | 30,055 (20,946) | 2,821 | $0.055 | 21 s |
| bunny_lowpoly-32 | en | 873 | 125 | 0 | 7 | 125 of 125 | 7 | 110,417 (91,520) | 5,010 | $0.116 | 37 s |
| Duo (3MF, local) | de | 1,025 | 153 | 0 | 5 | 153 of 153 | 5 | 106,508 (62,082) | 7,798 | $0.201 | 57 s |

- **Everything Claude answered passed mesh2brick's checks** in these runs (no task fell
  back). In development runs, the checks did reject merges; Claude used `stability_check`
  before answering and proposed only merges it had seen accepted.
- **Merges are rare:** the deterministic pass (ADR 0012) already merged the small steps,
  and most remaining neighbours cover each other's parts. The value is in the sections
  ("Stiel", "Hut unten", "Hut aufsetzen", "Weiße Punkte"; "Base", "Head", "Ear") and texts.
- **What made texts better (measured on the toadstool, same model):** telling Claude what
  each step's parts sit on ("sits on sub-assembly A") fixed wrong places ("behind the stem"
  for parts on top of the cap), and asking for the purpose of a step instead of a parts
  list made texts shorter. Passing the accepted section titles to the text task made
  texts use them ("the ear grows taller" instead of "the tower grows"). The first version
  cost $0.145 for the toadstool; with the model description as its own cache breakpoint it is $0.061.
- **One way of addressing the builder:** German texts mixed "Wir bauen" and "Setze"; the prompt now asks for direct instructions with "du" in every step.
- **Duo end to end:** 161 s including the LLM layer (target 5 minutes).

## v1.0 acceptance (Phase 8, 2026-11-07)

`uv run python scripts/benchmark_release.py --out out/release --local samples/...@32
--local samples/...@48` (SPEC §9). Every input runs through the real command line
(`python -m mesh2brick convert`) in its own process, one after the other, with the default
settings (longest axis 32 studs, `.mpd` + three parts lists + PDF); the time is the wall
clock of the whole process on an Apple M2 Max. Then the script checks every result: all
five files written, parts-list total = parts = parts in the strictly re-read LDraw file
("Checks"), and the model is one stable piece. The castle is a STEP file of eleven boxes
(wall ring, four towers, a keep, a courtyard slab) written by the script; it is converted
with `--config examples/mesh2brick.yaml`, the literal SPEC §9 command. "Estimate" is what
`mesh2brick inspect` predicts beforehand; "ratio" is placed parts per part of its quick fill
(see below).

| Input | Studs | Grid | Parts | Steps | Colours | One stable piece | Checks | PDF MB | Time s | Estimate | Ratio |
|---|---:|---|---:|---:|---:|---|---|---:|---:|---|---:|
| `bunny_lowpoly.stl` | 32 | 30x16x26 | 873 | 125 | 1 | yes | yes | 5.5 | 73 | 658 (455–1,012) | 1.73 |
| `cube_10mm.step` | 32 | 32x32x27 | 1,952 | 274 | 1 | yes | yes | 20.4 | 265 | 2,246 (1,555–3,456) | 1.13 |
| `cube_10mm.stl` | 32 | 32x32x27 | 1,952 | 274 | 1 | yes | yes | 20.4 | 265 | 2,246 (1,555–3,456) | 1.13 |
| `heart.vox` | – | 7x2x7 | 12 | 7 | 1 | yes | yes | 0.3 | 3 | 16 (11–24) | 1.00 |
| `l_bracket.stl` | 32 | 24x8x27 | 153 | 37 | 1 | yes | yes | 1.2 | 26 | 213 (148–328) | 0.93 |
| `rocket.blend` | 32 | 17x17x26 | 263 | 42 | 4 | yes | yes | 1.2 | 14 | 291 (202–448) | 1.17 |
| `sphere_r10.stl` | 32 | 32x32x27 | 1,499 | 207 | 1 | yes | yes | 10.1 | 113 | 1,746 (1,209–2,686) | 1.12 |
| `textured_cube.obj` | 32 | 32x32x27 | 2,280 | 327 | 2 | yes | yes | 23.2 | 294 | 2,246 (1,555–3,456) | 1.32 |
| `toadstool.obj` | 32 | 31x32x23 | 1,240 | 177 | 2 | yes | yes | 7.5 | 174 | 1,222 (846–1,880) | 1.32 |
| `torus.stl` | 32 | 32x32x6 | 552 | 74 | 1 | yes | yes | 4.1 | 15 | 515 (356–792) | 1.39 |
| `two_bodies.step` | 32 | 32x16x13 | 606 | 83 | 2 | yes | yes | 4.2 | 191 | 541 (374–832) | 1.46 |
| `vertex_colors.ply` | 32 | 32x32x27 | 1,519 | 212 | 4 | yes | yes | 9.9 | 124 | 1,747 (1,210–2,688) | 1.13 |
| `castle.step` (generated), `--config examples/mesh2brick.yaml` | 32 | 33x33x15 | 1,651 | 233 | 3 | yes | yes | 19.3 | 239 | 602 (417–926) | 3.57 |
| Duo (3MF, local only) | 32 | 32x19x24 | 1,025 | 153 | 5 | yes | yes | 7.0 | 100 | 757 (524–1,164) | 1.76 |
| Duo (3MF, local only) @48 | 48 | 48x31x35 | 2,313 | 326 | 5 | **no** | yes | 16.5 | 479 | 2,423 (1,678–3,728) | 1.24 |

- **Definition of Done met:** both STEP inputs (`cube_10mm.step`, 1,952 parts, and the castle
  with `--config`, 1,651 parts) produce `.mpd`, three parts lists and a PDF in under 5 minutes
  (265 s and 239 s). All fixtures are one stable piece and pass the checks.
- **Close to the limit:** closed bodies that fill the whole 32-stud box (the cubes:
  1,952–2,280 parts) take 265–294 s, so a slower laptop may need more than 5 minutes for
  them. Their PDFs are 20–23 MB (274–327 steps).
- **Beyond the target:** Duo at 48 studs has 2,313 parts, takes 479 s (legolization's final
  remerge cannot be bounded, UPSTREAM #5) and is **not** stable within the time limit. With
  `placement.time_limit_s=1200` the run had not finished after 63 minutes and was stopped.
- `.blend` costs about 1 s for Blender itself (`rocket.blend`: 14 s in total).
- `mesh2brick inspect` takes 2.5 s for the rocket and 15 s for Duo (2.1 million triangles:
  3MF reading and voxelization; the z-buffer picture of all triangles takes about 3 s).

**Part estimate of `inspect`.** A quick fill puts the largest brick that fits (2 x 8 down to
1 x 1, both orientations) on every free cell of every layer of the *solid* grid. Placement
then hollows the model and repairs stability, which adds parts: over the 15 runs above,
placed parts were 0.93–1.76 times the quick fill (median 1.3), except the castle (3.57),
whose thin courtyard slab legolization builds from plates (~250 plates per plate layer).
A first version based on cells of the hollow shell was much worse (0.07–0.42 parts per
cell, a factor of 6). `inspect` therefore shows 1.3 x the quick fill with the range
0.9–2.0 x; 14 of the 15 runs fall inside it.

## Size in centimetres (Roadmap 1, 2026-11-07)

`uv run mesh2brick inspect <model> --size <height>`; a size in cm means the height of the LEGO
model and is rounded to the nearest whole brick (`target layers`). "LEGO size" counts the
filled layers without the studs on top; the PDF cover adds the studs (1.7 mm).

| Model (file size, mm) | --size | target layers | grid (studs x studs x bricks) | LEGO size (cm) | estimate | converted |
|---|---|---:|---|---|---:|---|
| Duo (67.6 x 43.3 x 60.0, local only) | 20cm | 21 | 28 x 18 x 21 | 22.4 x 14.4 x 20.2 | 571 (395-878) | 799 parts, 45 s, stable |
| Duo | 30cm | 31 | 42 x 27 x 31 | 33.6 x 21.6 x 29.8 | 1,676 (1,160-2,578) | – |
| Duo | 40cm | 42 | 57 x 36 x 42 | 45.6 x 28.8 x 40.3 | 3,906 (2,704-6,010) | – (Roadmap 2) |
| L-bracket (30 x 10 x 40, CI) | 20cm / 30cm / 40cm | 21 / 31 / 42 | 19 x 6 x 21 / 28 x 9 x 31 / 38 x 13 x 42 | height 20.2 / 29.8 / 40.3 | – | – |
| Rocket (52 x 52 x 100) | 20cm | 21 | 13 x 13 x 20 | 10.4 x 10.4 x 19.2 | 179 (124-276) | – |
| Rocket | 30cm | 31 | 19 x 19 x 30 | 15.2 x 15.2 x 28.8 | 446 (309-686) | 376 parts, 31 s, stable |
| Rocket | 40cm | 42 | 26 x 26 x 40 | 20.8 x 20.8 x 38.4 | 606 (419-932) | – |

Duo and the L-bracket fill exactly the target layers, so their height is within half a brick
of the request. The rocket loses its top one or two layers: the tip of the nose fills less
than half a cell (`voxel.threshold`), the same rule that drops other thin details. `inspect`
shows the real height before converting. Duo at 40 cm (about 3,900 parts) is beyond the
5-minute budget; that is Roadmap 2 (hard time limit).

## Hard time limit (Roadmap 2, 2026-11-07)

**Where Duo at 48 studs spent more than an hour.** A run with periodic stack dumps showed the
time inside the *first* stability check after placement: one LP of 52,476 × 113,101 with about
1 million non-zeros for 2,392 parts. Captured and solved on its own (Apple M2 Max):

| HiGHS variant | Result |
|---|---|
| dual simplex with presolve (legolization's 1st attempt) | not solved in 180 s |
| dual simplex without presolve (2nd attempt) | not solved in 180 s |
| primal simplex | not solved in 180 s |
| interior point **with** crossover (3rd attempt, no time limit) | still running after 19 minutes (stopped) |
| interior point **without** crossover | **optimal in 48.6 s** |

Local patch #2 therefore tries the interior point method without crossover (300 s limit)
before legolization's last attempt. To check that it judges stability the same way, every
stability check of five placements was solved with the old attempt chain *and* without
crossover, and both force solutions were scored by legolization's own `_score`
(`compare_ipm.py`, not in the repository):

| Model (32 studs) | Stability checks | Solved by the old IPM with crossover | Same verdict |
|---|---:|---:|---:|
| `l_bracket.stl` | 19 | 0 | 19 |
| `bunny_lowpoly.stl` | 5 | 4 | 5 |
| `toadstool.obj` | 5 | 5 | 5 |
| `sphere_r10.stl` | 2 | 2 | 2 |
| Duo (local only) | 3 | 3 | 3 |

All 34 verdicts agree, including two unstable ones (bunny: 2 parts out of equilibrium in both).
The objective is the same within the solver tolerance; the per-part drag differs slightly where
the optimum is not unique (largest score 0.064 instead of 0.070 on the L-bracket). Every check
above about 800 parts needs the interior point method (both simplex attempts run into their
5 s limit). Up to 1,500 parts the crossover costs little (the old chain needed 17–33 s per
check, the new one 16–30 s); at 2,392 parts it is the difference between 49 s and more than an
hour.

**Release run with the hard limit** (`scripts/benchmark_release.py --out out/release-1.2 --local
samples/...@32 --local samples/...@48 --local samples/...@48:1200`, same laptop, one conversion
at a time). Every public input gives exactly the parts of 1.0 and stays one stable piece; none
is cut short. The time includes about 1 s for starting the placement process.

| Input | Parts (1.0) | Time s (1.0) | place s | PDF s | One stable piece | Cut short |
|---|---:|---:|---:|---:|---|---|
| `bunny_lowpoly.stl` | 873 (873) | 71 (73) | 54 | 15 | yes | no |
| `cube_10mm.step` | 1,952 (1,952) | 232 (265) | 188 | 42 | yes | no |
| `cube_10mm.stl` | 1,952 (1,952) | 232 (265) | 188 | 42 | yes | no |
| `heart.vox` | 12 (12) | 4 (3) | 2 | 0 | yes | no |
| `l_bracket.stl` | 153 (153) | 27 (26) | 23 | 2 | yes | no |
| `rocket.blend` | 263 (263) | 15 (14) | 10 | 3 | yes | no |
| `sphere_r10.stl` | 1,499 (1,499) | 109 (113) | 67 | 40 | yes | no |
| `textured_cube.obj` | 2,280 (2,280) | 246 (294) | 193 | 51 | yes | no |
| `toadstool.obj` | 1,240 (1,240) | 164 (174) | 134 | 28 | yes | no |
| `torus.stl` | 552 (552) | 16 (15) | 6 | 9 | yes | no |
| `two_bodies.step` | 606 (606) | 159 (191) | 148 | 9 | yes | no |
| `vertex_colors.ply` | 1,519 (1,519) | 118 (124) | 74 | 41 | yes | no |
| `castle.step` (generated), `--config` | 1,651 (1,651) | 202 (239) | 168 | 32 | yes | no |
| Duo (local only) @32 | 1,025 (1,025) | 95 (100) | 62 | 20 | yes | no |
| Duo (local only) @48, 300 s | 2,371 (2,313) | **289** (479) | 198 | 77 | no (one loose part) | **yes**, after placement and repair |
| Duo (local only) @48, 1,200 s | 2,308 (–) | **733** (> 3,780, stopped) | 645 | 74 | **yes** | no |

- **The 5-minute default holds for ≤ 2,000 parts** with room to spare (largest: the cubes,
  232 s); even the 2,280-part textured cube finishes in 246 s. The faster stability checks make
  most inputs a few seconds to 48 s faster.
- **The hard limit holds:** Duo at 48 studs with the default 300 s stops legolization after
  198 s (300 s minus voxelization and the export reserve for 2,371 parts) and finishes in 289 s.
  The cover says "Zeitgrenze erreicht" and, as the run had no stable state yet, "der letzte
  Zwischenstand".
- **Export reserve:** `export_reserve_s = 20 s + 0.03 s per part` keeps 51–91 s free for the
  inputs above 1,000 parts; LDraw, parts lists, PDF and preview needed 20–78 s there (Duo at 48
  studs: 77 s for 2,371 parts and five colours, the closest case). It stays as it is.
- **Duo at 48 studs with 1,200 s is one stable piece** after 733 s (2,308 parts): legolization
  finishes, and the one loose 1 x 1 brick its placement leaves under an overhang is removed
  and the stability checked again (about 60 s). Acceptance of #25 met.
- **Duo at 48 studs, earlier runs of this item** (1,200 s): before the voxel fix 608 s, 2,354
  parts, one loose 1 x 2 brick (the stub of two cells, one of which no part can hold); with the
  voxel fix but before removing loose parts 691 s, 2,309 parts, one loose 1 x 1 brick under the
  same overhang. legolization's placement and repair use their 300 s share; the rest is the
  first stability checks (about 60 s each), the final merge and the PDF.
- **Toadstool with a 120 s limit** (gallery picture): stopped during the final merge after 63 s,
  the state after placement and repair has the same 1,240 parts and is stable; 96 s in total.

**Slopes on the new path** (product-owner question: is the Phase 1 slope slowdown the same
crossover problem?). Low-poly bunny, `parts.categories=[brick, plate, slope]`, placement and
steps in one process, every LP attempt logged (`one_run.py`, not in the repository). "IPM
first" moves the crossover-free interior point attempt to the front, in the scipy path only or
also in the direct-highspy path legolization uses for step planning (not in mesh2brick yet).

| Case | 1.1 chain | 1.2 chain | IPM first (scipy) | IPM first (both paths) |
|---|---:|---:|---:|---:|
| 16 studs, `luo`, slopes (224 parts, 4 slopes) | 147 s | 147 s | 68 s | **17.5 s** |
| 16 studs, `luo`, no slopes (226 parts) | – | 7.8 s | – | 17.1 s |
| 32 studs, `kollsker`, slopes (873 parts, 14 slopes) | 108 s | 99 s | **49 s** | – |
| 32 studs, `kollsker`, no slopes (873 parts) | – | 53 s | – | 39 s |

- **Not the same problem, but the same cure.** On the 16-stud slope layout the LPs are small;
  simplex presolve hits its 5 s cap on 18 of 45 LPs (the stall of upstream #88), presolve-free
  simplex on 5 more, while the interior point method solves each of them in under 1 s (with or
  without crossover). The crossover never comes into play, so the 1.2 chain does not help.
- **IPM first makes slopes nearly free:** 17.5 s with slopes against 17.1 s without under the
  same order; 49 s for the 32-stud bunny with 14 slopes, faster than today's 53 s without.
  Every run gave the same layout as the 1.1 chain (parts, slopes, steps, stable).
- **But small easy LPs get slower:** simplex solves them in 0.1–0.4 s, the interior point
  method in 0.3–0.9 s (16 studs without slopes: 7.8 s → 17.1 s). A short simplex attempt
  (about 1 s) before the crossover-free interior point method should keep both; not measured.
- legolization's `preserve` mode adds few slopes at brick height (4 on 224 parts, 14 on 873):
  it only swaps exact profile matches. More slopes need Roadmap 8's candidate selection.

## Solver order and slopes back on (1.3.0, 2026-11-07)

Issue #34 (ROADMAP item 8, moved up by the product owner). Conditions: small models not noticeably
slower than in 1.2 (5 s cap per attempt stays); slopes on by default only if every fixture stays
one stable piece and needs at most twice its time without slopes.

**Attempt order, measured first** (`out/lp-order/one_run.py`, placement and steps in one process,
1.2 against the candidate orders; same layout means same parts, slopes, steps and verdict):

| Case | 1.2 | simplex 1 s, then IPM | simplex 3 s, then IPM | 3 s, step planning unchanged |
|---|---:|---:|---:|---:|
| L-bracket, 32 studs | 22.1 s | **28.0 s** (other steps) | 21.3 s | 21.3 s |
| torus, 32 studs | 5.3 s | **10.9 s** | 5.3 s | 5.3 s |
| rocket, bunny 16 (`luo` and `kollsker`) | 7.9 / 7.9 / 1.7 s | same | same | same |
| bunny 16, `luo`, slopes | 147 s | 34 s | 70 s | 99 s |
| bunny 32 | 78 s | 45 s | – | – |
| bunny 32, slopes | 74–99 s | 57 s | 63 s | 63 s |
| toadstool 32 | 135 s | 88 s | 99 s | 100 s |

Of 89 stability LPs that simplex solved in its first attempt under 1.2, 15 needed more than 1 s,
3 more than 2 s (longest 2.3 s; two more finished just under the 5 s cap). A 1 s cap therefore
sends ordinary LPs to the interior point method, which is slower on them and, in legolization's
step planning, returns more solutions near the stability boundary that get re-solved exactly
(L-bracket: 19 → 28 LPs, one step more). With 3 s the small models stay exactly as in 1.2. The
step-planning path needs the new order too (99 s instead of 70 s for the bunny with slopes).
Chosen: simplex 3 s → interior point without crossover 300 s → simplex without presolve 5 s →
legolization's last attempt, in both LP paths. Timings on this laptop vary by up to a third on the
big cases between runs (bunny 32 with slopes under 1.2: 99 s, later 74 s).

**Release run** (`scripts/benchmark_release.py --out out/release-1.3 --local samples/...@32`, then
the same with `--set "parts.categories=[brick, plate, slope]"`):

| Input | 1.2 | 1.3 | 1.3 with slopes | ratio | slopes placed | stable (1.3 / slopes) |
|---|---:|---:|---:|---:|---:|---|
| `bunny_lowpoly.stl` | 71 | 69 | 81 | 1.18 | 14 | yes / yes |
| `cube_10mm.step` | 232 | 216 | 220 | 1.02 | 0 | yes / yes |
| `cube_10mm.stl` | 232 | 214 | 222 | 1.04 | 0 | yes / yes |
| `heart.vox` | 4 | 4 | 4 | 0.98 | 0 | yes / yes |
| `l_bracket.stl` | 27 | 28 | 30 | 1.09 | 0 | yes / yes |
| `rocket.blend` | 15 | 16 | 19 | 1.20 | 0 | yes / yes |
| `sphere_r10.stl` | 109 | 97 | 126 | 1.30 | 46 | yes / yes |
| `textured_cube.obj` | 246 | 229 | 231 | 1.01 | 0 | yes / yes |
| `toadstool.obj` | 164 | 132 | 157 | 1.19 | 16 | yes / yes |
| `torus.stl` | 16 | 17 | 25 | 1.45 | 4 | yes / yes |
| `two_bodies.step` | 159 | 151 | 156 | 1.03 | 0 | yes / yes |
| `vertex_colors.ply` | 118 | 108 | 141 | 1.31 | 46 | yes / yes |
| `castle.step`, `--config` | 202 | 188 | 223 | 1.19 | 4 | yes / yes |
| Duo (local only) @32 | 95 | 77 | 78 | 1.00 | 0 | yes / yes |

Times in seconds; ratio = with slopes / without (1.3). All files, parts-list totals and strict
LDraw re-reads pass in both runs; none is cut short.

- **Small models are not slower:** at most +0.7 s (rocket), within run-to-run noise; bigger ones
  gain 8–32 s (toadstool 164 → 132 s, Duo 95 → 77 s).
- **Slopes cost at most 1.45x** (torus), 1.0–1.3x elsewhere; the 5-minute default holds (longest
  ≤ 2,000 parts with slopes: castle 223 s). Both conditions met: slopes are on by default.
- **Few slopes, and most of them inside:** legolization's `preserve` mode only swaps exact profile
  matches. Of the 130 slopes on the fixtures, 10 touch the outside (an empty cell connected to the
  outside next to one of their cells): bunny 4 of 14, toadstool 5 of 16, castle 1 of 4; sphere
  (46), vertex-colour model (46) and torus (4) have them all on the inner wall of the hollow
  shell. Slopes on cost little time but change little that a builder sees; placing more visible
  slopes is the 2.0 part of item 8.
- **Slopes are drawn as slopes** in previews, step pictures and part tiles (wedge from the stud
  row to a half-plate lip, as in LDraw's 3039, 3040b and 4286); the PDF of the bunny shows them in
  the callouts.

## Scalable stability checks (Roadmap 3, 2026-11-08)

Issue #26. `scripts/benchmark_sequencing.py` reads the finished layouts of the 1.3 release run back
(`out/release-1.3*/…/*.mpd`, strict LDraw import), so placement is not repeated, and runs only the step
planner, each input in its own process, one after the other. It counts legolization's LPs through its
telemetry (warm = re-solved on a growing model, cold = from scratch; "no LP" = a part not connected to
the ground, unstable without a solve). Duo at 48 studs uses the 2,308-part layout of the 1.2 release run.
Up to two runs at a time on the 12-core M2 Max; timings vary by about a fifth between runs.

**Measured first: legolization's search (`steps.sequencing=thorough`) with the 1.3 LP order.**

| Model | Parts | Sequencing | Steps (all checked) | States evaluated | LPs (warm / cold) | No LP | Steps that need a hand |
|---|---:|---:|---:|---:|---|---:|---:|
| torus | 552 | 100 s | 99 | 441 | 75 (30 / 45) | 366 | 41 |
| two bodies (STEP) | 606 | 34 s | 91 | 227 | 92 (86 / 6) | 135 | 0 |
| bunny | 873 | 392 s | 153 | 512 | 104 (30 / 74) | 408 | 60 |
| Duo @32 (local only) | 1,025 | 346 s | 193 | 866 | 100 (43 / 57) | 766 | 107 |
| toadstool | 1,239 | 415 s | 212 | 1,230 | 91 (23 / 68) | 1,154 | 158 |
| sphere | 1,499 | 776 s | 241 | 1,157 | 93 (22 / 71) | 1,064 | 155 |
| vertex colours (PLY) | 1,519 | > 1,200 s (stopped) | – | 1,146 by then | 90 (13 / 77) | 1,056 | – |
| castle (STEP) | 1,657 | 842 s | 264 | 324 | 259 (221 / 38) | 65 | 16 |
| STEP cube | 1,952 | 1,025 s | 291 | 474 | 292 (267 / 25) | 182 | 0 |
| textured cube | 2,280 | 613 s | 336 | 563 | 337 (327 / 10) | 226 | 0 |
| Duo @48 (local only) | 2,308 | > 1,500 s (stopped) | – | 1,843 by then | 73 (58 / 15) | 1,770 | – |

- **Result no. 1: the 1.3 order alone does not move the 500-part limit.** Duo at 32 studs needs
  346 s instead of about 400 s (Phase 2, old order), but after voxels, placement and the export reserve
  a 5-minute conversion leaves about 195 s for its steps. Only the two models around 600 parts would
  fit; above 870 parts the search takes 6–17 minutes or does not finish in 20.
- **Where the time goes** (phase profile, `profile_seq.py`): the greedy pass is almost free (bunny:
  52 warm probes in 0.1 s). Once no candidate is stable, the rescue re-plans the whole rest backwards
  with one cold LP of nearly the whole model per removal (bunny: 331 of 385 s, 49 LPs at 6.8 s; torus:
  56 of 102 s); the re-checks after forming sub-assemblies are cold too (torus 45 s, bunny 54 s). On the
  closed bodies a few huge LPs dominate (cube: the moment the hollow roof becomes load-bearing).
- **The search's plans need a hand often on hollow organic shapes** (last column: 40–75 % of the
  steps).

**The options of ROADMAP item 3** (planner-only seconds; "hand" = steps whose state needs a hand):

| Option | torus 552 | bunny 873 | Duo @32 1,025 | sphere 1,499 |
|---|---|---|---|---|
| search (baseline) | 100 s, 41 hand | 392 s, 60 hand | 346 s, 107 hand | 776 s, 155 hand |
| a1) no LP for parts resting on fully supported parts | 102 s; as a walk 96 s instead of 11 s | – | – | – |
| a2) warm re-checks after sub-assemblies | 68 s, same plan | – | – | – |
| a3) rescue only a window of bands (+ a2) | 61 s, 41 hand | > 670 s (stopped) | – | – |
| a4) no rescue: mark the step, go on (+ a2) | 19 s, 41 hand | 406 s, 57 hand | 135 s, 111 hand | – |
| b) blocks of ~200 parts planned alone, states then checked as in c3 | 23 s, 41 hand | 185 s, 66 hand | 286 s, 107 hand | 454 s, 155 hand |
| c1) rescue candidates in a pool of 4 | 106 s, 41 hand | – | – | – |
| c2) layer order + pre-assemblies, every state cold in a pool of 8 | 25 s, 0 hand | 76 s, 0 hand | 106 s, 0 hand | – |
| **c3)** as c2, one warm walker bottom-up + 7 cold workers top-down | 18 s, 0 hand | 67 s, 0 hand | 99 s, 0 hand | 268 s, 0 hand |
| d) as c3, but only every 4th state, bisect when unstable | 4 s* | 15 s, 32 of 125 checked | 21 s, 39 of 153 checked | 65 s, 52 of 207 checked |

\* on the plain layer order without pre-assemblies: 26 of 81 states unchecked, 16 of its 65 unstable
states missed. "–": not run, because the option had already lost on the smaller models.

- **a) incremental** does not pay off with legolization's warm LP model: skipping the LP for parts
  that rest fully on fully supported parts leaves them unsolved, and the next LP has to solve them all
  at once (torus walk 11 s → 96 s); a rescue window needs warm LPs of whole windows, which take
  thousands of simplex iterations each. Only a2 helps (and is exact), but the search stays far over
  the budget.
- **b) blocks** plan faster than the whole search but keep its steps that need a hand.
- **c) parallel** only helps where the work is independent: rescue candidates are not (first stable
  wins, warm state), the states of a fixed plan are.
- **d) every k-th state** is fast but leaves three quarters of the states unchecked; with the
  pre-assemblies there was nothing to bisect.

**Two accelerators for c3** (toadstool / sphere, planner only): cold workers skipping the simplex above
10,000 rows: 152 → 119 s / 268 → 196 s; 11 instead of 8 processes on top: 104 s / 176 s.

**Chosen (ADR 0017): c3 on every model above 500 parts** (planner-only, 8 processes, before the two
accelerators; the layer order and its pre-assemblies are those of 1.3, so parts and steps are
unchanged; search times from the first table). The end-to-end numbers are in the release run below.

| Model | Parts | Steps | Checked states | Need a hand | Checks | Search (1.3 order) | Left for steps in a 5-minute run |
|---|---:|---:|---:|---:|---:|---:|---:|
| torus | 552 | 74 | 74 | 0 | 18 s | 100 s (41 need a hand) | ~250 s |
| two bodies (STEP) | 606 | 83 | 83 | 0 | 22 s | 34 s (0) | ~120 s |
| bunny | 873 | 125 | 125 | 0 | 67 s | 392 s (60) | ~190 s |
| Duo @32 (local only) | 1,025 | 153 | 153 | 0 | 99 s | 346 s (107) | ~195 s |
| toadstool | 1,239 | 178 | 178 | 0 | 152 s | 415 s (158) | ~115 s |
| sphere | 1,499 | 207 | 207 | 0 | 268 s | 776 s (155) | ~150 s |
| vertex colours (PLY) | 1,519 | 212 | 212 | 0 | 283 s | > 1,200 s | ~140 s |
| castle (STEP) | 1,657 | 234 | 234 | 0 | 243 s | 842 s (16) | ~40 s |
| STEP cube | 1,952 | 274 | 274 | 0 | 460 s | 1,025 s (0) | ~45 s |
| textured cube | 2,280 | 327 | 327 | 0 | 707 s | 613 s (0) | ~35 s |
| Duo @48 (local only) | 2,308 | 325 | 325 | 0 | 919 s | > 1,500 s | ~440 s with `--time 20min` |

"Left for steps" = 5 minutes minus voxels, placement (1.3 release run) and the export reserve.

- **The layer order of 1.3 is the better plan:** with parts under overhangs pre-assembled, *no*
  intermediate state of any fixture needs a hand; legolization's search leaves 40–75 % of the steps
  of the hollow organic models needing one. The same holds for the small fixtures (rocket 0 instead
  of 11 of 46, L-bracket 0 instead of 1 of 40, heart 0 and 0), where the checks also take less time
  than the search (rocket 4 s instead of 8 s, L-bracket 6 s instead of 21 s); small models still use
  the search (unchanged instructions; product-owner question).
- **Every verdict is a full LP of exactly that state** (legolization's `analyze`, or its warm
  `PrefixSolver` with the boundary guard); nothing is inferred, so no state can be called stable
  without a check.
- **Cost per state** grows with its size, warm or cold: cold IPM 3.5 s at 473 parts, 6 s at 722,
  12 s at 964, 20 s at 1,239 (toadstool states); the simplex never finished in its 3 s above about
  470 parts (10,000 rows), so the cold workers skip it there; below, it is about as fast as the
  interior point (0.4–1.9 s against 0.5–2.1 s for 139–346 parts). A warm walk is milliseconds per state on
  simply stacked walls (cube: 245 states in 12 s) but 0.5–5 s on big hollow shells and degrades when
  a solve runs out of time.
- **Warm re-checks after sub-assemblies (a2) are exact:** same plan fingerprint as the search on the
  torus (`0b137a60af`), 117 s → 91 s in that run; an upstream candidate (#15), not used here.

**Release run 1.4** (`scripts/benchmark_release.py --out out/release-1.4`, defaults, one conversion at a
time, on AC power; in brackets 1.3 with slopes). Parts and steps are those of 1.3 for every input; the
small models (≤ 500 parts) still use legolization's search.

| Input | Parts | Time s (1.3) | Checked states | Need a hand | One stable piece |
|---|---:|---:|---:|---:|---|
| `heart.vox` | 12 | 4 (4) | 7 of 7 | 0 | yes |
| `l_bracket.stl` | 153 | 29 (30) | 37 of 37 | 1 | yes |
| `rocket.blend` | 263 | 19 (19) | 42 of 42 | 11 | yes |
| `torus.stl` | 552 | 36 (25) | **74 of 74** | 0 | yes |
| `two_bodies.step` | 606 | 166 (156) | **83 of 83** | 0 | yes |
| `bunny_lowpoly.stl` | 873 | 125 (81) | **126 of 126** | 0 | yes |
| `toadstool.obj` | 1,239 | 259 (157) | **178 of 178** | 0 | yes |
| `sphere_r10.stl` | 1,499 | 280 (126) | 180 of 207 | 0 | yes |
| `vertex_colors.ply` | 1,519 | 281 (141) | 155 of 212 | 0 | yes |
| `castle.step` (generated), `--config` | 1,657 | 265 (223) | 151 of 234 | 0 | yes |
| `cube_10mm.step` / `.stl` | 1,952 | 265 / 266 (220 / 222) | 126 / 125 of 274 | 0 | yes |
| `textured_cube.obj` | 2,280 | 266 (231) | 130 of 327 | 0 | yes |

All files, parts-list totals and strict LDraw re-reads pass; no model is cut short.

- **Every state checked within the 5-minute default** for every model up to 1,239 parts. Above that
  the checks fill the time left and stop at the hard limit: the sphere gets 87 % of its states, the
  vertex-colour model 73 %, the castle 65 %, the cubes 46 % and 40 % (their solid floors and roofs are
  made of many plates, so the bottom states alone are many steps). No checked state needs a hand.
- **Big models now use the time they are given:** a conversion that left 100–150 s unused in 1.3 now
  spends them on checks (bunny 81 → 125 s, toadstool 157 → 259 s); none goes over 281 s.
- The two Duo cases of this run were invalid (the laptop went to sleep with its lid closed, so the
  workers hardly got any CPU). Re-run awake on AC (`--skip-fixtures --out out/release-1.4-duo`, the
  castle runs too: 265 s, 150 of 234, as before):

| Input | Parts | Time s (1.3) | Checked states | Need a hand | One stable piece |
|---|---:|---:|---:|---:|---|
| Duo @32 (local only) | 1,025 | 139 (78) | **153 of 153** | 0 | yes |
| Duo @48, `--time 20min` (local only) | 2,308 | 1,189 (733 in 1.2) | 217 of 324 | 0 | yes |

- **Duo at 32 studs: every state checked within the 5-minute default** (acceptance of #26).
- **Duo at 48 studs with 20 minutes: two thirds.** Placement alone takes about 10 of the 20 minutes,
  and checking all states took 919 s with 8 processes on the finished layout; `--time 30min` should
  check all of them (estimate, not measured).

## PDF size (Roadmap 4, 2026-11-09)

Issue #27. `scripts/benchmark_pdf.py` writes the booklet of a finished model again (from the
`.bricks.json` of the 1.4 release run, so placement is not repeated) and counts every picture the
booklet renders by kind; the rest of the file is page content (text, vectors), fonts and structure.

**Where the bytes are (1.4):**

| Model | Parts | Steps | PDF MB | Step pictures MB | kB per step picture | Part tiles MB | Callouts MB | Cover MB | Rest MB | PDF time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| textured cube | 2,280 | 327 | 23.22 | 22.06 (95 %) | 67.5 | 0.10 | 0.13 | 0.54 | 0.39 | 54 s |
| STEP cube | 1,952 | 274 | 20.36 | 19.41 (95 %) | 70.8 | 0.10 | 0.14 | 0.36 | 0.35 | 44 s |
| sphere | 1,499 | 207 | 10.11 | 8.83 (87 %) | 42.7 | 0.11 | 0.66 | 0.32 | 0.20 | 44 s |
| bunny | 873 | 126 | 5.59 | 4.73 (85 %) | 37.5 | 0.11 | 0.28 | 0.27 | 0.20 | 17 s |
| rocket | 263 | 42 | 1.19 | 0.78 (66 %) | 18.6 | 0.11 | 0.01 | 0.17 | 0.12 | 3 s |

- **The step pictures are the PDF.** Part tiles, callouts, cover, text and fonts together are
  0.4–1.3 MB for every model.
- **A step picture's size follows the area the model covers** (correlation 0.72–0.91 with the share
  of non-background pixels; about 200 kB for a fully covered picture at 130 dpi): the cubes fill 38 %
  of their frame, sphere and bunny 20 %. The number of visible parts hardly matters (−0.19 to 0.68).
  What costs bytes are the edges: joint lines between parts and stud outlines, anti-aliased, then
  quantized to 64 colours.

**The levers, on single step pictures** (cube step 220, toadstool step 120, rocket step 30;
`out/pdf-size/levers/` has the pictures):

| Lever | Cube | Toadstool | Rocket | Look |
|---|---:|---:|---:|---|
| 1.4: median-cut palette, 64 colours, 130 dpi, anti-aliased | 41.1 kB | 33.1 kB | 15.5 kB | – |
| a) palette by fast octree, 64 colours | 24.0 kB | 24.8 kB | 11.3 kB | flat colours off by ≤ 1 level per channel, edges more exact than median cut |
| a) median cut with 32 / 24 colours | 32.7 / 28.8 kB | – | 12.3 / 11.7 kB | visible banding at 24 |
| a) zlib strategies and PNG row filters on top of Pillow | ≤ −1.5 % | ≤ −1.5 % | ≤ −2.7 % | – (Pillow is already near-optimal) |
| a) no anti-aliasing | 13.4 kB | – | – | jagged edges, joints look heavier: a visible change |
| b) 110 / 100 / 90 dpi (with octree) | 18.9 / 16.6 / 14.8 kB | 19.9 / 17.0 / 14.7 kB | – | softer, part still clear at 100 |
| c) vector paths (PDF, Flate) | 602 kB | 556 kB | 106 kB | vectors win only below about 120 polygons (one or two parts: heart step 1 1.4 kB against 2.0 kB) |
| d) faded parts without joints (octree, 130 dpi) | 11.2 kB | 16.6 kB | – | earlier parts as plain faces with studs; new parts stand out more |
| d) … and without studs on faded parts | 7.6 kB | 11.4 kB | – | no studs left to count positions on: rejected |

**Whole booklets** (`benchmark_pdf.py --compact on --dpi …`; MB):

| Variant | Textured cube | STEP cube | Castle | Sphere | Vertex model |
|---|---:|---:|---:|---:|---:|
| 1.4 | 23.22 | 20.36 | 19.35 | 10.11 | 9.91 |
| octree palette, 130 dpi | 18.83 | 12.57 | 10.26 | 7.09 | 8.73 |
| octree, 110 dpi | 15.01 | 10.16 | 8.05 | 5.80 | 7.12 |
| octree, 100 dpi | 12.98 | 8.60 | 7.25 | 5.19 | 6.35 |
| octree + faded parts without joints, 130 dpi | 11.84 | 7.65 | 6.41 | 5.17 | 6.64 |
| **octree + faded parts without joints, 110 dpi (chosen)** | **9.45*** | **6.31*** | – | – | – |
| octree + faded parts without joints, 100 dpi | 8.10 | 5.26 | – | – | – |

\* `--dpi` also lowers the cover picture here; as shipped only the step pictures change (textured
cube 9.56 MB, STEP cube 6.39 MB, see below).

- **Only with the faded parts drawn without joints does the textured cube get below 10 MB** without
  going below 100 dpi; its two-colour pattern makes many more edges than the plain cube. The product
  owner chose it for big models only (2026-11-09; comparison page in `out/pdf-size/`): models above
  500 parts get faded parts without joints, the octree palette and 110 dpi; small models keep the
  pictures of 1.4 pixel for pixel (ADR 0018).
- Drawing fewer polygons also makes the booklet faster: textured cube 54 → 31 s.

**1.5 rule on every booklet** (`benchmark_pdf.py` on the 1.4 models, compact by size; MB, 1.4 in
brackets; step pages of heart, L-bracket and rocket pixel-identical to 1.4):

| Model | Parts | PDF MB | kB per step picture | PDF time |
|---|---:|---:|---:|---:|
| heart, L-bracket, rocket | 12–263 | 0.29 / 1.22 / 1.19 (same) | 13–23 (same) | same |
| torus | 552 | 1.98 (4.11) | 17.8 | 6 s |
| two bodies | 606 | 2.24 (4.22) | 18.6 | 6 s |
| bunny | 873 | 2.62 (5.59) | 14.0 | 10 s (17) |
| Duo @32 (local only) | 1,025 | 3.68 (6.99) | 15.2 | 12 s |
| toadstool | 1,239 | 3.88 (7.61) | 13.5 | 17 s |
| sphere | 1,499 | 4.39 (10.11) | 15.0 | 24 s (44) |
| vertex model | 1,519 | 5.58 (9.91) | 19.1 | 25 s |
| castle | 1,657 | 5.11 (19.35) | 17.7 | 20 s |
| STEP cube | 1,952 | 6.39 (20.36) | 19.8 | 26 s (44) |
| textured cube | 2,280 | 9.56 (23.22) | 25.7 | 31 s (54) |
| Duo @48 (local only) | 2,308 | 7.61 (16.43) | 17.0 | 39 s |

**Release run 1.5** (`scripts/benchmark_release.py --out out/release-1.5 --local …@32 --local …@48:1200`,
on AC power, lid open; in brackets 1.4). Parts, steps and pages as in 1.4 for every input; all files,
parts-list totals and strict LDraw re-reads pass; no warning above 40 kB per step.

| Input | Parts | Steps | PDF MB | kB per step | PDF s | Time s | Checked states |
|---|---:|---:|---:|---:|---:|---:|---:|
| `heart.vox` | 12 | 7 | 0.29 (0.29) | 42.0 | 0 | 4 (4) | 7 of 7 |
| `l_bracket.stl` | 153 | 37 | 1.22 (1.22) | 32.9 | 3 | 30 (29) | 37 of 37 |
| `rocket.blend` | 263 | 42 | 1.19 (1.19) | 28.3 | 3 | 18 (19) | 42 of 42 |
| `torus.stl` | 552 | 74 | 1.98 (4.11) | 26.8 | 5 | 33 (36) | 74 of 74 |
| `two_bodies.step` | 606 | 83 | 2.24 (4.22) | 27.0 | 6 | 163 (166) | 83 of 83 |
| `bunny_lowpoly.stl` | 873 | 126 | 2.62 (5.59) | 20.8 | 9 (16) | 120 (125) | 126 of 126 |
| Duo @32 (local only) | 1,025 | 153 | 3.74 (6.99) | 24.4 | 11 | 128 (139) | 153 of 153 |
| `toadstool.obj` | 1,239 | 178 | 3.88 (7.61) | 21.8 | 16 (29) | 250 (259) | 178 of 178 |
| `sphere_r10.stl` | 1,499 | 207 | 4.39 (10.11) | 21.2 | 24 (43) | 261 (280) | 172 of 207 |
| `vertex_colors.ply` | 1,519 | 212 | 5.58 (9.91) | 26.3 | 24 (44) | 260 (281) | 156 of 212 |
| `castle.step` (generated), `--config` | 1,657 | 234 | 5.11 (19.35) | 21.8 | 19 (32) | 251 (265) | 151 of 234 |
| `cube_10mm.step` / `.stl` | 1,952 | 274 | 6.39 (20.36) | 23.3 | 26 (42) | 250 (265) | 123 of 274 |
| `textured_cube.obj` | 2,280 | 327 | 9.56 (23.22) | 29.2 | 31 (52) | 245 (266) | 125 of 327 |
| Duo @48, `--time 20min` (local only) | 2,308 | 324 | 7.61 (16.43) | 23.5 | 37 (76) | 1,151 (1,189) | 214 of 324 |

- **Every booklet below 10 MB**, the closed bodies by a factor of 2.4–3.8. Small models are unchanged
  byte for byte in their step pictures (step pages pixel-identical to 1.4; the cover differs only in
  date and version).
- **The PDF takes 40–50 % less time** for big models; conversions finish 9–21 s earlier, because
  the step checks keep their time (the export reserve depends on the part count, not on the PDF).
  Checked states move by a few between runs (sphere 172 instead of 180, cube 123 instead of 126).

## Part estimate (Roadmap 5, 2026-11-10)

Issue #28, ADR 0019. Measured on the 15 runs of the 1.5 release (`out/release-1.5`: the saved voxel
grid and the placed parts of every input), without converting again; then legolization's own
telemetry on three of them, and seven small synthetic models placed with `mesh2brick place` to test
the rules on shapes they were not tuned on. `uv run python scripts/benchmark_estimate.py --results
out/release-1.5` prints the table below in seconds.

**Why the fixed factors could not work.** The 1.5 estimate filled the *solid* grid with the
largest bricks and took 0.9 / 1.3 / 2.0 times that. Placed parts were 0.93–1.76 times the fill,
except the castle (3.58). Taking the hollow shell instead (suggested in the issue) makes it worse
for boxes (cube 3.13, two bodies 2.57), because what decides the count is somewhere else:

- **legolization works on plates.** It hollows at plate resolution and builds a brick only where a
  column is filled in one colour across a whole three-plate slab; the rest becomes plates (curved
  surfaces leave many such partial slabs). Retracing exactly that — the hollowing is identical to
  legolization's `core_mask` on all 14 grids and wall 1–3 — and filling each layer largest-first
  gives the count of legolization's first tiling: two bodies 236 = 236; organic models 0.88–1.27 of
  the final count.
- **Joining rebuilds.** What the first tiling leaves in separate pieces is joined by rebuilding the
  area from 1 × 1 plates and merging them at random (telemetry `place.tiled` → `place.connected`):

  | Model | Tiled parts | Pieces | After joining | Final |
  |---|---:|---:|---:|---:|
  | castle | 581 | 20 | 1,653 | 1,657 |
  | STEP cube | 910 | 5 | 1,952 | 1,952 |
  | two bodies | 236 | 2 | 1,711 | 606 (final merge wins it back as small bricks) |

- **Where it happens** can be read off the grid: areas one cell high with nothing above or below
  (castle courtyard, Duo's base: 197 plates where the fill puts 31 bricks, a table top) always
  become three layers of plates, 0.66–0.81 parts per cell (1 stud × 1 brick). Hollow floors at most
  `wall` cells thick are always rebuilt too; up to about 30 × 30 studs they end up as small bricks
  (0.18–0.24 parts per cell) or stay plates (0.52–0.82), wider ones stayed plates (0.66–0.87). Which of
  the two happens is not a matter of width alone (the 24-stud box: bricks when 10 cells high, plates
  when 27 high), so the estimate does not try to predict it:

  | Hollow box (studs, 10 high unless noted) | Bottom layer | Placed | Floor rebuilt as | Parts per floor cell |
  |---|---:|---:|---|---:|
  | 16 × 12, 8 high, two colours ("seam") | 192 | 77 | not rebuilt (floor 96 studs) | – |
  | 18 × 18 | 324 | 255 | small bricks | 0.24 |
  | 24 × 24 | 576 | 348 | small bricks | 0.18 |
  | 24 × 24, 27 high | 576 | 950 | plates | 0.52 |
  | 28 × 28 | 784 | 1,466 | plates | 0.82 |
  | 32 × 32 | 1,024 | 1,629 | plates | 0.69 |
  | STEP cube 32 × 32 × 27 | 1,024 | 1,952 | plates | 0.71 |

  A colour seam alone (two bodies of different colours side by side) is not a reason: the
  two-colour box was joined at no extra cost.

**The new estimate** (`voxel/estimate.py`): the plate-level fill outside rebuilt areas
× 0.85 / 1.0 / 1.35, plus per rebuilt cell 0.55 / 0.7 / 0.9 for thin areas (one cell high, pieces
above 16 studs) and, for a weak floor (at least 150 studs of the bottom layer at most `wall` cells
thick), by the size of the bottom layer's largest piece: below 1,000 studs 0.15 / 0.45 / 0.9
(either outcome), from 1,000 studs 0.55 / 0.7 / 0.9 (plates).

| Input | Parts | 1.5 estimate | New estimate | In range | Width | Thin cells | Floor cells |
|---|---:|---|---|---|---:|---:|---:|
| `bunny_lowpoly.stl` | 873 | 658 (455–1,012) | 670 (570–905) | yes | 1.59 | 0 | 0 |
| `cube_10mm.step` / `.stl` | 1,952 | 2,246 (1,555–3,456) | 1,930 (1,548–2,513) | yes | 1.62 | 0 | 2,048 |
| `heart.vox` | 12 | 16 (11–24) | 12 (10–16) | yes | 1.60 | 0 | 0 |
| `l_bracket.stl` | 153 | 213 (148–328) | 153 (130–207) | yes | 1.59 | 0 | 0 |
| `rocket.blend` | 263 | 291 (202–448) | 299 (254–404) | yes | 1.59 | 0 | 0 |
| `sphere_r10.stl` | 1,499 | 1,746 (1,209–2,686) | 1,587 (1,349–2,142) | yes | 1.59 | 0 | 0 |
| `textured_cube.obj` | 2,280 | 2,246 (1,555–3,456) | 1,940 (1,556–2,526) | yes | 1.62 | 0 | 2,048 |
| `toadstool.obj` | 1,239 | 1,222 (846–1,880) | 1,281 (1,089–1,729) | yes | 1.59 | 0 | 0 |
| `torus.stl` | 552 | 515 (356–792) | 599 (509–809) | yes | 1.59 | 0 | 0 |
| `two_bodies.step` | 606 | 541 (374–832) | 633 (300–1,154) | yes | 3.85 | 0 | 1,024 |
| `vertex_colors.ply` | 1,519 | 1,747 (1,210–2,688) | 1,587 (1,349–2,142) | yes | 1.59 | 0 | 0 |
| `castle.step` (generated), `--config` | 1,657 | **602 (417–926)** | 1,718 (1,384–2,242) | yes | 1.62 | 476 | 1,225 |
| Duo @32 (local only) | 1,025 | 757 (524–1,164) | 907 (753–1,224) | yes | 1.63 | 225 | 34 |
| Duo @48 (local only) | 2,308 | 2,423 (1,678–3,728) | 2,342 (1,740–3,478) | yes | 2.00 | 0 | 1,080 |

- **15 of 15 inside the range** (1.5: 14), the range on average a factor **1.78** wide instead of
  2.22: 1.59–1.63 for every model without a mid-sized hollow floor, 2.0 for Duo at 48 studs and 3.85
  for two bodies. The expected value is within 0.88–1.30 of the placed count for all 15 runs.
- **Not tuned on:** Duo at 20 cm (799 parts; 646, 536–871) and the rocket at 30 cm (376; 401,
  341–541) from Roadmap 1, and the synthetic seam (77; 76, 65–103), table (317; 297, 235–383) and
  boxes (18: 255; 174–705, 24: 348; 295–1,231, 24 high: 950; 469–1,507,
  28: 1,466; 392–1,660, 32: 1,629; 1,317–2,146) are all inside.
- **Time advice** ("recommended: --time 20min" above 2,000 expected parts): among the test models
  only Duo at 48 studs (expected 2,342). The STEP cube and the textured cube had it in 1.5 (expected
  2,246) and lose it; they finish in about 250 s.
- **Speed:** the estimate takes 0.3–43 ms per test model (1.5: 0.1–33 ms), `inspect` takes 2.5–15 s.
  Shells above 500,000 plate cells fall back to 4 cells per part (0.6–1.6); a sphere of 128 studs
  (1.1 million cells, 320,000 shell plate cells) is still estimated exactly in 1.3 s, random noise
  of the same shell size in about 1.2 s. The 1.5 fallback applied above 400,000 *solid* cells.

## Shape fidelity baseline (2.0, 2026-11-10)

The metric of the 2.0 series (ROADMAP: "surface deviation to the input mesh, and part count, at
unchanged stability"), issue #42. `mesh2brick.fidelity` measures how far the **outside of the brick
model** lies from the mesh it was made from:

- in real LEGO millimetres (8 mm per stud, 3.2 mm per plate), so every model size compares;
- only faces towards the air around the model (the cavity of a hollow model does not count);
- **studs included** with their real size (4.8 mm wide, 1.7 mm high); tiles and the sloped columns
  of slopes have none, slopes are sampled on their sloped face;
- sampled about every 2 mm, each sample weighted by the area it stands for, and measured exactly to
  the nearest triangle of the input mesh (unsigned; overlapping shells such as the bunny's ellipsoids
  count as they are). Voxel inputs (`heart.vox`) are compared with their own cells.

Reported: the area-weighted **mean** and **95th percentile** ("95 % of the surface is at most this
far away"), in mm and studs. The metric is one-sided: it says how far the parts stick out or fall
short where there are parts, not whether a thin detail of the mesh is missing (a candidate for
ROADMAP 10/11, which add material).

Baseline: the 1.6 models (placement unchanged since 1.5), from the saved results of the 1.5
release run without converting again:
`uv run python scripts/benchmark_fidelity.py --results out/release-1.5 --local samples/Duo_Duolingo.3mf`.
"Without studs" is the same model with every stud removed: the most tiles could ever win.
`scripts/benchmark_release.py` records the numbers per run from now on (column "Deviation mm").

| Input | Parts | Mean mm | p95 mm | Mean studs | p95 studs | Without studs: mean / p95 mm | s |
|---|---:|---:|---:|---:|---:|---|---:|
| `bunny_lowpoly.stl` | 873 | 2.04 | 4.50 | 0.254 | 0.562 | 1.96 / 4.39 | 2.4 |
| `cube_10mm.step` / `.stl` | 1,952 | 0.83 | 4.05 | 0.104 | 0.506 | 0.54 / 3.20 | 2.2 |
| `heart.vox` | 12 | 0.08 | 0.85 | 0.010 | 0.106 | 0.00 / 0.00 | 0.0 |
| `l_bracket.stl` | 153 | 0.60 | 4.05 | 0.075 | 0.506 | 0.39 / 3.20 | 0.8 |
| `rocket.blend` | 263 | 1.46 | 3.18 | 0.182 | 0.398 | 1.45 / 3.18 | 3.2 |
| `sphere_r10.stl` | 1,499 | 2.35 | 4.82 | 0.294 | 0.603 | 2.05 / 4.57 | 2.6 |
| `textured_cube.obj` | 2,280 | 0.83 | 4.05 | 0.104 | 0.506 | 0.54 / 3.20 | 2.3 |
| `toadstool.obj` | 1,239 | 2.03 | 4.58 | 0.254 | 0.572 | 1.95 / 4.46 | 4.6 |
| `torus.stl` | 552 | 1.95 | 4.48 | 0.244 | 0.560 | 1.91 / 4.46 | 2.8 |
| `two_bodies.step` | 606 | 0.66 | 3.20 | 0.083 | 0.400 | 0.62 / 3.20 | 0.5 |
| `vertex_colors.ply` | 1,519 | 2.36 | 4.85 | 0.295 | 0.607 | 2.06 / 4.53 | 2.6 |
| `castle.step` (generated), `--config` | 1,657 | 3.31 | 8.00 | 0.414 | 1.000 | 3.27 / 8.00 | 7.5 |
| Duo @32 (local only) | 1,025 | 1.86 | 4.23 | 0.233 | 0.529 | 1.85 / 4.23 | 26.0 |
| Duo @48 (local only) | 2,308 | 1.76 | 4.29 | 0.220 | 0.536 | – | 32.7 |

**Reading:**

- **Boxes** (cubes, L-bracket) lie closest on average (0.6–0.8 mm), but their 95th percentile is
  4.05 mm: the top is one plate (3.2 mm) above the mesh, because 32 studs of height are 26.7 bricks
  and the voxels round to 27, and the studs on it add up to 1.7 mm. Without studs it would be the
  plate alone (3.20 mm).
- **Round shapes** (sphere, bunny, torus, toadstool, Duo): 1.8–2.4 mm on average, 4.2–4.9 mm at the
  95th percentile; that is the voxel stairs (half a stud wide, a brick high). Studs make up only
  0.04–0.3 mm of it, on the sphere the most (its many stair tops).
- **Castle:** 3.31 / 8.00 mm. Its boxes overlap, so the STEP mesh is not watertight and voxelization
  falls back to "every cell the surface touches": the walls stand one stud proud on two sides.
  A voxelization matter, not one of the parts (note for later, no issue yet).
- **Heart** (voxel input, compared with its own cells): only the studs, 0.08 / 0.85 mm.
- **Cost:** 0.5–7.5 s per fixture (Duo with its 2.1 million triangles 26–33 s), against 4–260 s
  for the conversion; it runs in the release benchmark, not in `convert`.

## Tiles (ROADMAP 9, 2026-11-10)

Issue #42, ADR 0020. All runs: `scripts/benchmark_release.py` with
`--set "parts.categories=[brick, plate, slope, tile]"` and Duo at 32 studs (`--local`), on the
development laptop. "1.6" is the 1.5 release run (`out/release-1.5`, placement unchanged since),
its deviation from "Shape fidelity baseline" above. Run-to-run noise: models without a single tile
vary by up to ±5 % in time and ±10 % in checked states between runs (sphere 158–172 of 207).

**legolization's own pass** (`apply_tiles`, `tile` in `parts.categories` up to now; laptop on
battery for this run, 0–7 % slower than the others):

| Input | Tiles | Where | Deviation mean / p95 mm (1.6) |
|---|---:|---|---|
| sphere, vertex-colour sphere | 184, 172 | on the level stairs | 2.35 / 4.82, 2.36 / 4.85 (same) |
| toadstool, bunny, torus | 117, 61, 56 | on the stairs | same within 0.01 mm |
| Duo @32 | 93 | stairs and base | 1.86 / 4.23 (same) |
| castle | 69 | courtyard plates only, patchy (1 × 1, 1 × 2, 1 × 4, 2 × 2) | 3.32 / 8.00 (3.31 / 8.00) |
| rocket, L-bracket | 9, 1 | stray plates | same |
| cubes, textured cube, two bodies, heart | 0 | – (their tops are bricks) | same |

It never touches bricks, only knows four tile sizes, and tiles stairs as readily as box tops: no
model got closer to its mesh. Every model stayed one stable piece; the cubes ran into the time limit
on battery (best so far, no intermediate state checked), which the later runs on mains power did not.

**mesh2brick's pass** (flat tops from the mesh, tiles where the face is; final code):

| Input | Tiles | How | Parts 1.6 → tiles | Deviation mean / p95 mm, 1.6 → tiles | One stable piece | Time s 1.6 → tiles | Checked states 1.6 → tiles | PDF MB |
|---|---:|---|---|---|---|---|---|---:|
| `bunny_lowpoly.stl` | 0 | – | 873 → 873 | 2.04 / 4.50 → 2.04 / 4.50 | yes | 120 → 122 (+1 %) | 126/126 → 126/126 | 2.62 |
| `cube_10mm.step` | 139 | 118 brick(s) -> plate + tile, a plate lower | 1,952 → 2,091 (+139, +7 %) | 0.83 / 4.05 → 0.00 / 0.00 | yes | 250 → 248 (-1 %) | 123/274 → 124/294 | 6.38 |
| `cube_10mm.stl` | 139 | 118 brick(s) -> plate + tile, a plate lower | 1,952 → 2,091 (+139, +7 %) | 0.83 / 4.05 → 0.00 / 0.00 | yes | 249 → 247 (-1 %) | 123/274 → 125/294 | 6.38 |
| `heart.vox` | 2 | 2 brick(s) -> 2 plates + tile | 12 → 16 (+4, +33 %) | 0.08 / 0.85 → 0.06 / 0.00 | yes | 4 → 4 (+2 %) | 7/7 → 9/9 | 0.34 |
| `l_bracket.stl` | 24 | 12 brick(s) -> plate + tile, a plate lower | 153 → 177 (+24, +16 %) | 0.60 / 4.05 → 0.00 / 0.00 | yes | 30 → 36 (+20 %) | 37/37 → 40/40 | 1.29 |
| `rocket.blend` | 0 | – | 263 → 263 | 1.46 / 3.18 → 1.46 / 3.18 | yes | 18 → 18 (-4 %) | 42/42 → 42/42 | 1.19 |
| `sphere_r10.stl` | 0 | – | 1,499 → 1,499 | 2.35 / 4.82 → 2.35 / 4.82 | yes | 261 → 260 (-0 %) | 172/207 → 181/207 | 4.39 |
| `textured_cube.obj` | 186 | 173 brick(s) -> plate + tile, a plate lower | 2,280 → 2,466 (+186, +8 %) | 0.83 / 4.05 → 0.00 / 0.00 | yes | 245 → 242 (-1 %) | 125/327 → 127/354 | 9.83 |
| `toadstool.obj` | 0 | – | 1,239 → 1,239 | 2.03 / 4.58 → 2.03 / 4.58 | yes | 250 → 250 (+0 %) | 178/178 → 178/178 | 3.88 |
| `torus.stl` | 0 | – | 552 → 552 | 1.95 / 4.48 → 1.95 / 4.48 | yes | 33 → 33 (-2 %) | 74/74 → 74/74 | 1.98 |
| `two_bodies.step` | 96 | 74 part(s) with a tile on top, a plate higher | 606 → 702 (+96, +16 %) | 0.66 / 3.20 → 0.00 / 0.00 | yes | 163 → 177 (+9 %) | 83/83 → 97/97 | 2.44 |
| `vertex_colors.ply` | 0 | – | 1,519 → 1,519 | 2.36 / 4.85 → 2.36 / 4.85 | yes | 260 → 260 (+0 %) | 156/212 → 154/212 | 5.58 |
| `castle.step` (generated), `--config` | 99 | 76 plate(s) -> tile, 5 plate(s) -> 2+ tiles, 6 brick(s) -> plate + tile, a plate lower, 1 brick(s) -> 2 plates + tile | 1,657 → 1,676 (+19, +1 %) | 3.31 / 8.00 → 3.25 / 8.00 | yes | 251 → 250 (-0 %) | 151/234 → 142/236 | 5.09 |
| Duo @32 (local only) | 22 | 21 part(s) with a tile on top, a plate higher | 1,025 → 1,047 (+22, +2 %) | 1.86 / 4.23 → 1.81 / 4.23 | yes | 128 → 134 (+5 %) | 153/153 → 156/156 | 3.79 |

**Variants** (same command; tiles and parts are what the final code places, times and checked states
of these two runs come from the first version, which checked stability before planning):

| Variant | Input | Tiles | Parts (1.6 → variant) | Deviation mean / p95 mm |
|---|---|---:|---|---|
| `parts.tiles=all` (stairs too) | sphere | 86 | 1,499 → 1,665 (+166) | 2.35 / 4.79 (default rule: 2.35 / 4.82) |
| | toadstool | 107 | 1,239 → 1,420 (+181) | 2.01 / 4.51 (2.03 / 4.58) |
| | bunny | 55 | 873 → 961 (+88) | 2.03 / 4.47 (2.04 / 4.50) |
| | castle | 149 | 1,657 → 1,738 (+81) | 3.20 / 8.00 (3.25 / 8.00) |
| `parts.tiles_on_base=false` | castle | 13 | 1,657 → 1,671 (+14) | 3.23 / 8.00 |
| | Duo @32 | 0 | 1,025 → 1,025 | 1.86 / 4.23 (with base: 1.81 / 4.23) |

**Reading:**

- **Boxes now match their mesh**: cubes, textured cube, L-bracket and two bodies 0.00 / 0.00 mm
  (1.6: 0.66–0.83 / 3.20–4.05). Studs gone, and the tiles lie where the face is: the cubes and the
  L-bracket are 26.7 bricks high, so a brick under the face becomes one plate plus a tile (the top one
  plate lower than the voxels); the two bodies are 13.3 bricks high, so the bricks get a tile on top.
- **Round shapes are untouched** with the default rule (sphere, bunny, toadstool, torus, rocket,
  vertex-colour sphere: 0 tiles). Tiles on their stairs (`parts.tiles=all`) cost 88–181 parts and
  move the deviation by at most 0.07 mm: the stairs are a voxel matter, not a stud matter.
- **Castle**: courtyard, wall, tower and keep tops get 99 tiles; its p95 stays at 8 mm because of
  the voxelization (open STEP mesh, see "Shape fidelity baseline"). **Duo**: only the base ring is
  flat (22 tiles laid on it); without base tiles Duo gets none.
- **Stability, time, PDF:** every run is one stable piece. Time against 1.6 −4 % to +9 %, except the
  L-bracket: 30 → 36 s (+20.4 %), its 24 extra parts go through legolization's step search, which
  models up to 500 parts use. Big models check about as many intermediate states as in 1.6 (cube
  124 of 294, castle 142 of 236); the textured cube's PDF is 9.83 MB (below 10 MB; 1.6: 9.56 MB).
  `inspect`'s estimate still contains every count (14 of 14, without a tile term).
- **Castle towers and Duo's base keep part of their studs:** a part gets tiles only when its whole
  top lies under the flat face. The castle's voxels stand a stud beyond the towers (open mesh), and
  Duo's base ring has a curved edge, so the parts along those edges keep their studs; on Duo the
  tiles laid on the inner parts stand a plate above them.
- **First version for comparison** (two plates + tile under every face, stability checked before
  the steps): textured cube +359 parts, 304 s (4 s over the limit), PDF 10.3 MB, no intermediate
  state checked; castle and cube without checked states; Duo 164 s. Hence ADR 0020's two changes:
  tiles where the face is (textured cube +186 parts, 244 s, 9.8 MB) and the check beside the step
  planning (Duo 138 s, castle 135 checked states).

## Tile share per face (issue #44, 2026-11-11)

Product owner's rule (ADR 0020, amendment): a flat face gets tiles only if at least 85 % of its open
top can be tiled, otherwise all of it keeps its studs. Same command as "Tiles (ROADMAP 9)", mains
power; "1.7.0" is that section's final run.

| Input | Tiles 1.7.0 → 85 % rule | Faces kept | Parts 1.6 → 1.7.0 → 85 % rule | Deviation mean / p95 mm, 1.7.0 → 85 % rule | One stable piece | Time s 1.6 → 85 % rule |
|---|---|---:|---|---|---|---|
| `cube_10mm.step` / `.stl` | 139 → 139 | 0 | 1,952 → 2,091 → 2,091 | 0.00 / 0.00 → 0.00 / 0.00 | yes | 250 → 250 |
| `textured_cube.obj` | 186 → 186 | 0 | 2,280 → 2,466 → 2,466 | 0.00 / 0.00 → 0.00 / 0.00 | yes | 245 → 244 |
| `l_bracket.stl` | 24 → 24 | 0 | 153 → 177 → 177 | 0.00 / 0.00 → 0.00 / 0.00 | yes | 30 → 38 |
| `two_bodies.step` | 96 → 96 | 0 | 606 → 702 → 702 | 0.00 / 0.00 → 0.00 / 0.00 | yes | 163 → 185 |
| `heart.vox` | 2 → 2 | 5 | 12 → 16 → 16 | 0.06 / 0.00 → 0.06 / 0.00 | yes | 4 → 5 |
| `castle.step` (generated), `--config` | 99 → **0** | 14 | 1,657 → 1,676 → 1,657 | 3.25 / 8.00 → 3.31 / 8.00 | yes | 251 → 252 |
| Duo @32 (local only) | 22 → **0** | 2 | 1,025 → 1,047 → 1,025 | 1.81 / 4.23 → 1.86 / 4.23 | yes | 128 → 130 |
| sphere, vertex sphere, bunny, toadstool, torus, rocket | 0 → 0 | 0 | unchanged | unchanged | yes | ±2 % (bunny 146 s once, 120 s rerun with and without tiles) |

Every face of the castle and Duo stays below 85 %, and always for the same reason: parts that reach
past the edge of the flat face (shares from the placed layouts, `out/tiles/share`):

| Model | Face | Open cells | Tileable | Not tileable: part reaches past the face |
|---|---|---:|---:|---:|
| castle | courtyard | 366 | 254 (69 %) | 112 |
| castle | keep roof | 60 | 32 (53 %) | 28 |
| castle | 4 wall tops | 54 each | 16 (30 %) each | 38 each |
| castle | 4 tower tops | 36 each | 0–3 (0–8 %) | 33–36 each |
| castle | 4 small courtyard corners | 18 each | 1–13 (6–72 %) | 5–17 |
| Duo @32 | base ring (two faces) | 78 each | 40 (51 %), 26 (33 %) | 38, 52 |

No fitting tile, colour or time ever was the reason. The castle's voxels stand a stud beyond its
walls and towers (open STEP mesh, surface voxelization), and Duo's base ring has a curved edge, so
the bricks and plates along those edges cover flat and non-flat cells at once. Time: the rule plans
every part before changing any (a few milliseconds); the slower runs above (L-bracket 38 s, two
bodies 185 s) are run-to-run noise of this run, the bunny without a single tile took 146 s once and
120 s twice afterwards.

**Reading:** the rule does what it says: no face is half tiled any more. On the fixtures it leaves
the boxes as in 1.7.0 and takes all tiles off the castle and Duo. To tile those faces, the parts
along their edges would have to be split at the face's edge (the part inside gets a smooth top, the
rest keeps studs); that is not part of #44.
