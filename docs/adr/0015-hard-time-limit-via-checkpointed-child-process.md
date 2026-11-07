# 15. Hard time limit: legolization in a child process with checkpoints

- Status: accepted
- Date: 2026-11-07
- Extends: [ADR 0006](0006-time-bounded-conversion.md)

## Context

ADR 0006 made `placement.time_limit_s` the budget for a whole conversion, but only as a
strong target: legolization 0.5.0 bounds placement and repair (`time_budget_s`), not its
stability checks, refill rounds and final merge, and Python cannot interrupt them from the
outside. Duo at 48 studs needed 479 s with the 300 s default; with 1,200 s it was still
running after 63 minutes. Measured on 2026-11-07: the time goes into the **first stability
check after placement**, one linear program (LP) of 52,476 × 113,101 for 2,392 parts. None of
HiGHS' simplex variants solves it in 180 s, and the interior-point method (IPM), legolization's
last attempt, has no time limit (our local patch #2 limits all attempts but the last) and was
still running after 19 minutes. The IPM itself converges in 49 s; the time goes into its final
"crossover" to an exact corner solution. Roadmap 2 asks for a hard limit: a stable model or an
honest "best so far" within the time limit.

## Decision

- **legolization runs in a child process** whenever there is a deadline (always in
  `convert`). The child reports every layout legolization reaches: before each stability
  check ("unchecked"), after placement and repair, after each refill round of weak hollow
  parts, after the final merge, and the finished result. The parent waits until the deadline
  minus the time kept for the export, then **terminates the child**: a hard stop, wherever
  legolization is (also inside HiGHS).
- **The best state wins:** checked and buildable (stable, one piece) beats checked but
  unstable, which beats not checked; among equals the latest. A finished run keeps its
  result unless only an earlier state is buildable (then legolization's last passes made the
  model worse, and the stable one is used, with a note).
- **Honest marking:** a model the limit cut short carries `best_so_far` (brick-model schema
  4). The PDF cover says "time limit reached: the best stable model found by then" or, without
  a stable state, "the last intermediate result" next to the existing stability verdict; an
  unchecked model shows "Stability: not checked". The command line names the stage and part
  count. If the limit hits before any layout exists, the conversion fails with a clear
  message (raise the limit or make the model smaller).
- **The export keeps its share:** the stop time is `deadline − export_reserve_s(parts)`
  with the part count of the latest state, so `.mpd`, parts lists, PDF and preview still fit.
  The LLM layer is skipped (with a note) when less than 30 s remain before the export.
- **Large stability checks get a faster path:** local patch #2 now tries the IPM without
  crossover (300 s limit) before legolization's last attempt. It finds the same optimum within
  the solver tolerance; legolization scores the forces it returns as before. On all 34
  stability checks of five placements (L-bracket, bunny, toadstool, sphere, Duo at 32 studs)
  its stable/unstable verdicts match the old attempt chain's (docs/benchmarks.md).
- **Cells no part can hold are removed during voxelization** (with a note): a cell that
  sticks out sideways, where no straight brick or plate reaches a cell with something above
  or below, would always give a loose part. This made Duo at 48 studs unbuildable (one cell
  of a two-cell stub); no other test model has such cells.
- **A few loose parts are removed after placement:** if up to three parts of the finished run
  are not connected to the ground (legolization put a lone 1 x 1 brick under Duo's overhang),
  the child removes them and checks the stability again; the unchanged result is reported
  first, so it counts if the limit stops the re-check. More loose parts stay, with the
  existing note, because removing them would change the model visibly.
- The hook is a documented local patch: during `run()` mesh2brick wraps legolization's
  `pipeline._phase_gauge` (its per-phase readings) and `pipeline.analyze`; an import-time
  check fails loudly if they disappear (docs/UPSTREAM.md #5).

## Consequences

- The limit holds for every model size: legolization can no longer run for an hour. Every
  conversion pays about 1 s for starting the child (it imports legolization again); a run
  without a deadline (`place`, tests) stays in-process.
- A model cut short usually has more parts than a finished one (the final merge saves parts)
  or is not stability-checked; the cover and the command line say so, and a higher
  `placement.time_limit_s` gives the full optimisation.
- Layouts are pickled through a pipe at every checkpoint (a few per run, well under a second
  each for 2,000 parts).
- Upstream, a phase callback and a time limit for every stability check and the final merge
  in `run()` would make the patch unnecessary (candidate #5).
