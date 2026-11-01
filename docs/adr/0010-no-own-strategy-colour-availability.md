# 10. No own placement strategy; parts LEGO does not make are kept out before placement

- Status: accepted
- Date: 2026-11-01

## Context

SPEC Phase 5: benchmark all legolization strategies on the fixtures (runtime, part count,
stability). Build an own strategy behind the `Placer` protocol, or open an upstream PR,
only if gaps are measurable. Record the decision as an ADR.

The product owner added a second topic. Phase 4 showed that the real test model needs 2 x 8
and 1 x 8 bricks in Bright Green, which LEGO does not make. Two remedies were to be compared
on that model:

- **split afterwards:** replace such bricks by shorter ones of the same colour and re-check
  stability (interim solution),
- **restrict beforehand:** placement knows what exists, so such parts are never chosen.

Measurements are in docs/benchmarks.md (Phase 5).

## Decision

**No own strategy.** All 7 strategies on 6 fixtures (16 studs) and 3 fixtures (32 studs):

- Every completed run was buildable.
- `kollsker` had the fewest parts in 6 of 9 cases and is the fastest or close to it
  everywhere.
- Other strategies beat it on single models:
  - `smga` on the torus and the toadstool at 16 studs,
  - `beauty`, `fast` and `bond` on the bunny at 32 studs,
  - `bond`, `fast` and `beauty` also on the toadstool at 16 studs.
- The biggest savings (`smga`, `beauty`) cost 2-5x the time, and both time out on other
  models.

The gaps are trade-offs between existing strategies, not missing placement capability, so an
own strategy would not close them. `kollsker` stays the default.

**Colour availability: `parts.availability`**, default `exclude`:

- `exclude`: before placement, parts that LEGO does not make in one of the model's colours
  are left out for the whole model.
  - Exceptions: the 1 x 1 fillers stay (legolization needs them), and the slopes go all
    together or not at all.
  - Data: Rebrickable elements from the offline table (ADR 0009).
- `split`: after placement, each such brick or plate is split along its long side into
  existing shorter parts of the same width, height and colour (`place/split.py`).
  - Fewest pieces, and joints away from joints directly above and below.
  - Two 1-wide rows as a fallback.
  - Exact coverage is enforced; a failed replacement is rolled back; stability is analysed
    again.
- `report`: only flag them in the parts list (Phase 4 behaviour).

On the real model, `exclude` beat `split` on every measure: 1,025 vs 1,049 parts, 70 vs
130 s, both stable with no parts that do not exist. The cause: legolization plans with the
shorter bricks from the start instead of having its long bricks cut up afterwards.

## Addendum: Studio check, thin walls and joint offsets (2026-11-01)

The product owner checked the owl in BrickLink Studio:

- no overlaps, no duplicates, no stability issues;
- 31 clutch-power hints, on one wing and the feet.

He asked whether a minimum wall thickness or an offset pattern for thin walls is needed.
Measurements are in docs/benchmarks.md ("Studio check").

- **Stability:** legolization agrees with Studio. The model is stable; its highest loads
  (at most 2 % of a stud's clutch capacity) sit at the wing tip and the legs, where Studio
  marks clutch hints. Nothing hangs on a single weak connection; the largest group behind
  one brick is 3 bricks.
- **Minimum wall thickness: no.** The wings are mostly 2–3 studs thick, and only 25 of
  1,013 bricks lie in 1-stud walls. Thickening would change the shape for little gain.
- **Offset pattern: no own pass.** 41 % of vertical joints continue through a brick
  interface. None of legolization's levers changes that, and a post-pass that re-cuts rows
  of equal bricks reached only 41 → 40 %. Bond-aware placement is upstream candidate #11.
  The metric `stacked_joints` stays, to measure future changes.

## Consequences

- Parts lists of default conversions contain only part/colour pairs LEGO makes. The
  exceptions are 1 x 1 fillers, the only parts that cannot be excluded or split, and pairs
  without Rebrickable data (unknown counts as available).
- `exclude` acts per model, not per colour: a part missing in one colour is also left out
  for the other colours of that model. For the test model that cost nothing (Bright Green
  dominates). A per-colour restriction needs legolization to accept allowed parts per
  colour. That is the follow-up to upstream #8, recorded as candidate #9.
- `split` remains available for models where the global exclusion costs too many parts.
- Picking the best existing strategy per model within the time budget stays possible later
  without new placement code.
