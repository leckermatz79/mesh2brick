# 16. Stability-LP attempt order, and slopes on by default

- Status: accepted
- Date: 2026-11-07
- Extends: [ADR 0015](0015-hard-time-limit-via-checkpointed-child-process.md) (local patch #2)

## Context

Slopes were switched off in Phase 1 because legolization 0.5.0 became up to 50 times slower with
them (upstream #88). Measured on 2026-11-07, the cause is the order of the stability-LP attempts,
not the slope pass: on slope layouts HiGHS' simplex stalls in presolve (and sometimes without
it), while the interior-point method without crossover solves the same LPs in under a second.
Large LPs show the same pattern (both simplex attempts run into their cap on every LP above about
800 parts). Trying the interior-point method *first* fixes slopes but makes small, easy models
slower (simplex solves those in 0.1–2.3 s). The product owner moved this part of ROADMAP item 8
to 1.3.0 with two conditions: small models must not get noticeably slower, and slopes go on by
default only if every fixture stays stable within twice its time without slopes.

## Decision

- **Attempt order in both LP paths** (scipy `linprog` and legolization's direct highspy path for
  step planning): simplex with presolve, 3 s; interior point without crossover, 300 s; simplex
  without presolve, 5 s (the existing cap); legolization's last attempt without a limit. 3 s is
  above the longest of 89 measured easy simplex solves (2.3 s); 1 s was measured and rejected
  (L-bracket +27 %, torus 2x). In the direct path the first run falls back to the
  interior-point method inside the same call, so legolization's loop stays unchanged.
- **Slopes on by default** (`parts.categories: [brick, plate, slope]`), because the release run
  met both conditions: every fixture one stable piece, at most 1.45x the time (torus), small
  models within run-to-run noise of 1.2 and big ones faster.
- **Slopes drawn as slopes:** `PlacedPart.studs` (brick-model schema 5) records a slope's stud
  row; the renderer draws the sloped columns as a wedge down to a half-plate lip, as in LDraw.

## Consequences

- Big models and slope layouts convert faster (toadstool 164 → 132 s, Duo at 32 studs
  95 → 77 s, bunny at 16 studs with slopes and `luo` 147 → 70 s); small ones as before.
- Slopes are cheap but rare and mostly invisible: legolization's `preserve` mode only swaps exact
  profile matches, and 120 of the 130 slopes on the fixtures sit on the inner wall of hollow
  shells. More visible slopes need our own candidate selection (ROADMAP item 8, 2.0 part).
- The interior-point solution is optimal but not a vertex; per-brick drag can differ slightly
  where the optimum is not unique. All 34 compared verdicts agreed (ADR 0015).
- Upstream, the same order would remove most of the patch; it was suggested on legolization #89.
