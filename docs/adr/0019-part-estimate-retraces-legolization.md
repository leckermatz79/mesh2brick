# 19. The part estimate retraces legolization

- Status: accepted
- Date: 2026-11-10
- Replaces: the estimate of Phase 8 (`voxel/estimate.py`: quick fill of the solid grid × 0.9 / 1.3 / 2.0)

## Context

`mesh2brick inspect` and the start of `convert` show an expected part count, and from 2,000 expected
parts the advice "recommended: --time 20min" (product owner, 2026-11-07). Up to 1.5 the estimate
filled the *solid* voxel grid with the largest bricks and multiplied by fixed factors; 14 of the 15
release runs fell inside its range (factor 2.2 wide), the castle did not (602 estimated, 1,657 placed).
ROADMAP item 5 (issue #28) asks for 15 of 15 and a narrower range on average.

Measured before deciding (docs/benchmarks.md, "Part estimate (Roadmap 5)"), on the saved grids and
parts of the 1.5 release run and with legolization's own telemetry:

- legolization builds on plates. It hollows the grid at plate resolution (`core_mask`: `wall` studs
  sideways, `wall` cells up and down) and makes a brick only where a column is filled in one colour
  across a whole three-plate slab; everything else becomes plates. Retracing exactly that and
  filling every layer with the largest parts that fit gives the count of legolization's first tiling:
  two bodies 236 = 236, organic models within 0.88–1.27 of the final count.
- The big misses all come from one later step. What the tiling leaves in separate pieces (castle: 20,
  STEP cube: 5, two bodies: 2), legolization joins by rebuilding the area from 1 × 1 plates and
  merging them at random: castle 581 → 1,653 parts, cube 910 → 1,952, two bodies 236 → 1,711 (its
  final merge wins most of it back: 606).
- Where that happens is visible in the grid. Areas one cell high with nothing above or below (the
  castle courtyard, Duo's base, a table top) always become three layers of plates, 0.66–0.81 parts
  per cell. Floors at most `wall` cells thick over a wide area (hollow boxes) are always rebuilt too.
  Floors of 32 × 32 studs and more stayed plates (cubes, a flat box, castle: 0.66–0.87 per cell);
  smaller ones ended up as small bricks (boxes 18 and 24 studs wide, two bodies: 0.18–0.24) or as
  plates (the 24-stud box when 27 instead of 10 cells high, a 28-stud box: 0.52–0.82). Which of the
  two happens could not be predicted from the shape.
- A first rule for colour seams (two bodies of different colours side by side) did not hold: a
  smaller two-colour box was joined at no extra cost.

## Decision

The estimate retraces legolization: plate-resolution hollowing identical to `core_mask` (a test
compares both), bricks on full one-colour slabs, a colour-aware largest-first fill per layer, and two
rebuild terms counted per cell instead of by the fill: thin areas (one cell high, pieces above 16
studs) at 0.55 / 0.7 / 0.9 parts per cell, and a weak floor (at least 150 studs of the bottom layer
are at most `wall` cells thick) at 0.15 / 0.45 / 0.9 when the bottom layer's largest piece is below
1,000 studs (either outcome) and 0.55 / 0.7 / 0.9 above (plates). The fill itself gets
0.85 / 1.0 / 1.35. Low, expected and high are the sums. The range is therefore narrow wherever the
outcome is foreseeable (factor 1.6) and wide only where legolization's own outcome varies (hollow
floors up to about 30 × 30 studs, factor 2–4).

Grids whose shell has more than 500,000 plate cells are estimated from the shell size (4 cells per
part, 0.6–1.6); the old fallback looked at the solid grid above 400,000 cells. The fill now runs
over the shell only, so much bigger models are estimated exactly (a 128-stud sphere: 1.3 s).

## Consequences

- 15 of 15 release runs inside the range, on average a factor 1.78 wide instead of 2.22 (12 of 15:
  1.6). The castle is 1,718 (1,384–2,242) instead of 602 (417–926); the expected value is within
  0.88–1.30 of the placed count for all 15. Not tuned on and also inside: Duo at 20 cm, the rocket at
  30 cm, a table, a two-colour box and five hollow boxes.
- The time advice now appears only for Duo at 48 studs (expected 2,342) among the test models; the
  cubes (expected 1,930 / 1,940, placed 1,952 / 2,280) lose it, and they finish within 5 minutes.
- For small hollow floors the expected value is the middle of two outcomes (the boxes placed
  0.53–1.65 times as many parts); the range covers both.
- The estimate depends on legolization's behaviour. After an upgrade, re-check it without
  converting: `uv run python scripts/benchmark_estimate.py --results out/release`.
- No change to placement, steps or PDF.
