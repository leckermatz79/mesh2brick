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
