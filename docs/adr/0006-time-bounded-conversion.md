# 6. Time-bounded conversion

- Status: accepted
- Date: 2026-11-01

## Context

The product owner set a budget: a conversion may take 5 minutes, and the first real model
(~1,100 parts at 32 studs) must finish within it. legolization 0.5.0 bounds placement and repair
with `time_budget_s`, but not its final remerge or step sequencing. Sequencing checks the
stability of every intermediate state and took ~400 s for that model with the best strategy
alone. Python cannot interrupt the sequencer from the outside (docs/benchmarks.md).

## Decision

`placement.time_limit_s` (default 300) is the budget for the whole conversion. The adapter
runs legolization's pipeline **without** its sequencer and plans steps itself:

- **`steps.sequencing: auto`** (default) uses stability-checked steps up to 500 parts and
  bottom-up layer chunks above that. Layer order is always insertable from above, but
  overhangs may need a hand. `thorough`, `fast` and `layers` can be forced.
- **Checked sequencing runs in a child process.** It is terminated when the remaining
  budget, minus a reserve for LDraw, BOM and PDF, is used up. The result then falls back to
  layer order, and the CLI says so.
- **Default strategy is `kollsker`**, measured fastest at similar part counts.
- **legolization's `time_budget_s` defaults to 25 % of the budget**, which bounds placement
  and repair.

## Consequences

- The real model converts within the budget: placement ~90 s, plus import, voxels and PDF.
- Large models get layer-order instructions with a note, not stability-checked ones. Better
  sequencing for big models is a Phase 5/6 topic, possibly upstream (a time budget for
  remerge and sequencing).
- The final remerge stays unbounded, so the budget is a strong target, not a hard guarantee.
  Exceeding it is reported.
- Starting a child process costs a few seconds (it imports legolization again). This only
  happens for checked sequencing with a deadline.
