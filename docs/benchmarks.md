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
  remerge cannot be bounded, UPSTREAM #5) and is **not** stable within the time limit.
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
