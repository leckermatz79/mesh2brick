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
