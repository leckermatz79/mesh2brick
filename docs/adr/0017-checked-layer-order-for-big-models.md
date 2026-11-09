# 17. Big models: layer order, every intermediate state checked in parallel

- Status: accepted
- Date: 2026-11-08
- Replaces the 500-part rule of [ADR 0006](0006-time-bounded-conversion.md); keeps the hard limit of
  [ADR 0015](0015-hard-time-limit-via-checkpointed-child-process.md)

## Context

Since Phase 2, `steps.sequencing: auto` used legolization's stability-checked step search up to
500 parts and an unchecked layer order above. The 500 came from measurements before the 1.3 LP
attempt order (ADR 0016). Roadmap 3 asks for checked intermediate states on big models within the
time limit, or an honest statement how many were checked.

Measured first (docs/benchmarks.md, "Scalable stability checks (Roadmap 3)"), with the 1.3 order:

- **The new order alone does not move the limit.** legolization's search needs 34–100 s at about
  600 parts, 346 s for Duo at 32 studs (Phase 2: about 400 s) and 392–1,025 s for the other
  fixtures between 873 and 1,952 parts; the vertex-colour model and Duo at 48 studs did not finish
  in 20 and 25 minutes. After placement, a 5-minute conversion leaves 40–250 s for steps.
- **Where the time goes:** its greedy pass costs almost nothing (bunny: 0.1 s). When no candidate
  is stable, a rescue re-plans the *whole rest* of the model backwards, with one LP of nearly the
  whole model per removal, solved from scratch (bunny: 331 of 385 s, 49 LPs); re-checking the steps
  after forming sub-assemblies adds more cold LPs (torus: 45 s). On closed bodies (cubes, castle)
  a few huge LPs dominate, when a hollow roof becomes load-bearing.
- **And its plans need a hand often on hollow organic shapes:** 60 of 153 steps on the bunny, 107
  of 193 on Duo, 158 of 212 on the toadstool, 155 of 241 on the sphere. mesh2brick's own layer
  order with parts under overhangs pre-assembled (Phase 6, ADR 0012) has **no** step that needs a
  hand on any fixture, as the checks below show, the small ones included (rocket: 0 instead of 11
  of 46, L-bracket: 0 instead of 1 of 40).

The four options of the roadmap, measured on the torus, the bunny, Duo at 32 studs and the sphere:

| Option | What was measured | Result (bunny / Duo @32 / sphere) |
|---|---|---|
| a) incremental | skip the LP for parts resting with every stud socket on fully supported parts; warm re-checks after sub-assemblies; rescue only a window of bands | skipping leaves the parts unsolved and the next LP slower (torus walk 11 → 96 s); warm re-checks are exact but save only a third (torus 100 → 68 s); the window is slower (bunny > 670 s) |
| b) blocks | ~200-part blocks planned alone by legolization, states then checked | 185 / 286 / 454 s, but 66 / 107 / 155 steps need a hand |
| c) parallel | rescue candidates in a pool: no gain (torus 106 s); **every state of the layer order with pre-assemblies on its own, warm walker bottom-up + cold workers top-down** | **67 / 99 / 268 s, every state checked, none needs a hand** |
| d) every k-th state | k = 4 on the same layer order, bisect when unstable | 15 / 21 / 65 s, but only 32 / 39 / 52 of 125 / 153 / 207 states checked |

legolization's search for comparison: 392 / 346 / 776 s, 60 / 107 / 155 steps need a hand. Two
accelerators for c) (cold workers skip the simplex above 10,000 rows; 11 instead of 8 processes)
bring the toadstool from 152 to 104 s and the sphere from 268 to 176 s.

A warm walk (one LP model that grows with the plan, as legolization's `verify_plan`) is fastest
on small and simply stacked states (milliseconds per state on a cube's walls), but on big hollow
states each step costs thousands of simplex iterations, a warm solve that runs out of time leaves
a bad start for the next, and a walk cannot be split across processes (a segment that starts in
the middle needs a full solve first, which costs as much as checking it cold).

## Decision

- **`auto` chooses by size and time** (`steps/budget.py`): legolization's search for models up to
  500 parts *if* its estimated time (5.2 × 10⁻⁴ s × parts², the measured upper bound) fits 75 % of
  the time left; otherwise **checked layers**: the layer order of 1.3 with pre-assemblies, then
  every intermediate state checked. A search that does not finish in its 75 % falls back to
  checked layers in the rest. The 500 no longer decides *whether* states are checked (the time
  does); it only keeps small models' instructions as in 1.3 (legolization's order and
  sub-assemblies, approved with 1.0). Switching them too would be faster and need a hand less
  often; that is the product owner's call (STATUS, questions).
- **The checks run in parallel** (`backends/checks.py`): one *walker* checks states bottom-up with
  a warm LP (legolization's `PrefixSolver`, primal simplex, 5 s per solve), the other workers check
  states top-down, each with its own LP from scratch; they meet in the middle. States with a part
  that no stud connection links to the ground are unstable without an LP (legolization's own
  shortcut). The pool has all cores but one, at most 12 (11 on the 12-core laptop, 10–13 % faster than 8); above about 460 parts the cold workers go
  straight to the interior-point method (the simplex never finished in its 3 s there).
- **Hard limit unchanged:** the checks get the time left before the export reserve; then every
  worker is terminated. States checked by then keep their verdict, the others stay unchecked.
- **Honest reporting:** all states checked: a note with the count and how many steps need a hand,
  no cover sentence (as for small models); some: the cover says "There was time to check k of n
  intermediate states (all of the bottom L of A layers)" and the command line names the counts;
  none: the 1.3 sentence. `steps.sequencing: checked-layers` forces the new path, `layers` the
  unchecked one.

## Consequences

- Big models get the steps of 1.3 (same order, same pre-assemblies, same part count) plus real
  verdicts: where a state does not stand, the step says "hold the model", from legolization's own
  stability model. Every verdict is a full LP of exactly that state; nothing is inferred.
- Within the 5-minute default every state is checked for every fixture up to 1,239 parts (torus,
  two-body STEP, bunny, toadstool; the small ones as before); above that the checks fill the time
  left: sphere 87 %, vertex-colour model 73 %, castle 65 %, cubes 46 % (release run 1.4). The cover
  says how many; `--time 20min` checks all of them.
- Big conversions now take longer (bunny 81 → 125 s, toadstool 157 → 259 s): the time 1.3 left
  unused goes into the checks; none went over 281 s.
- A conversion uses several cores for up to a few minutes; each worker imports legolization once
  (about 1 s). Which worker checks a state depends on timing, so in rare degenerate cases a verdict
  could differ between a warm and a cold solve, the same tolerance legolization accepts between its
  own engines.
- Upstream: warm re-checks after sub-assemblies, a time limit for warm prefix solves, and the
  rescue scope are candidates #15–#17 in docs/UPSTREAM.md.
