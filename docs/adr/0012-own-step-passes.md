# 12. Own step passes: hanging parts with their holder, even step sizes, MPD by default

- Status: accepted
- Date: 2026-11-07

## Context

- **Studio check (product owner):** step sizes vary between 1 and 6 parts; step 87 of the
  real test model places a single 1 x 1 plate.
- **Own measurement:** models above 500 parts get layer-order steps without stability
  checks (accepted in Phase 2, see `steps.sequencing`). In that order a part under an
  overhang is placed before the part above it that holds it. In the real model 155 of
  1,025 parts hang in the air for 1–16 steps; a builder following the steps would see
  them fall off.
- SPEC Phase 6: sub-assemblies as MPD sub-models with their own steps.
- legolization's sub-assembly extraction targets exactly this, but on layer-order plans it
  finds one 530-brick "cluster" (floating runs overlap) and would re-run a stability LP per
  step, which costs minutes on large models.

## Decision

Two backend-neutral passes in `steps/` run on the backend's plan (`refine_plan` in the
legolization backend):

1. **Hanging parts** (only for unchecked layer-order plans): which part holds which is
   derived from cells alone (a part sitting on another in a stud column). A part that is
   not connected to the table when its step is done moves into the step that first holds
   it, and forms a *unit* with its holder: put it together in the hand, then place both.
   The PDF shows each unit from below in a small "first" box. Checked plans are left
   alone: there legolization's own verdicts and sub-assemblies apply.
2. **Even step sizes:** a step with fewer than half of `steps.parts_per_step` parts is
   merged into its neighbour if both build the same thing (main model or the same
   sub-assembly), neither attaches a sub-assembly, the result has at most
   `parts_per_step + 3` parts, and every part of the earlier step stays at least half
   visible. In layer-order plans, steps that grew above that limit are first cut into
   spatially coherent pieces between groups of parts that do not touch.

Verdicts carry over: a merged step is stable only if all its original steps were, and
ROTSTEP view hints are summed.

**`mpd` replaces `ldr` in the default `output.formats`.** It keeps legolization's
sub-assemblies as LDraw sub-models with their own steps (SPEC Phase 6 and the v1.0
definition of done); `ldr` stays available and flattens them as before.

## Consequences

On the real test model (1,025 parts): hanging parts 155 → 0, steps with fewer than 3 parts
11 → 4, largest step 9 → 10, 164 → 153 steps. The pass takes 0.1 s. The remaining small
steps are large plates that the next step covers. Details in docs/benchmarks.md (Phase 6).

- Layer-order plans still carry no stability verdicts. The cover says so in plain words.
- Units whose way in from above is blocked are counted (`blocked`); in all measured models
  there were none.
- Slopes count as studded on top in the structure, which overstates their grip slightly
  (they are opt-in).
- The passes are generally useful for legolization's layer-order fallback; this is
  recorded as upstream candidate #12.
