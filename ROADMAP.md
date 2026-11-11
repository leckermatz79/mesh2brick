# mesh2brick – Roadmap after 1.0

Status: draft by the product owner, 2026-11-07; updated 2026-11-07 after Roadmap 2 (item 8 split: its speed part
moved to 1.x as 1.3.0), 2026-11-10 (2.0 order: 9 before 8) and 2026-11-11 (issues #44 and #46 before 8). Lives in the repo root next to SPEC.md.
SPEC.md stays the source of truth for *how* we work; this file says *what* comes next and in which order.
Claude Code: treat each numbered item as a candidate issue. Before starting one, write the acceptance
criteria into the issue, as in Phases 0–8.

## Guiding decisions (from the product owner)

- 2.0 is primarily for the owner's family builds, not for a wide audience. Usability for strangers comes later.
- Models will actually be built, so cost awareness matters, but "expensive" is decided ad hoc per model.
- A personal brick inventory is **out of scope** (no inventory exists; a brick sorter would be a separate project).
  Any inventory feature must stay optional and never block a nicer model that needs missing parts.
- The fork-or-wait question for legolization is **not decided yet**. It is decided by the first 2.0 item that
  depends on an unanswered upstream PR: if hbmartin has not responded by then, implement behind the
  `Placer` protocol ourselves or fork; the owner makes that call when it comes up.

---

## 1.x – make large models work (minor releases, no new brick types)

Goal: whatever size the user asks for, they get a stable model or an honest "best so far" within the time limit.

1. **Size in centimetres as a first-class option.** `input.target_height_cm` (or longest edge) in config and CLI,
   converted to studs internally; cover page already shows dimensions. Acceptance: Duo at 20, 30 and 40 cm
   produce the expected stud counts; `inspect` shows the resulting size before conversion.
2. **Hard time limit across the whole pipeline.** legolization's final optimisation ignores the limit (Duo at
   48 studs: >1 h). Wrap every backend stage with a deadline; on expiry return the best *stable* model found,
   mark it on the cover page as in Phase 2. Acceptance: Duo at 48 studs finishes in ≤ 20 min with a stable model
   or a clear report; the 5-minute default stays for ≤ 2,000 parts.
3. **Scalability of stability checks.** Large models (>500 parts) currently get layer-order steps without
   intermediate stability checks. Options to benchmark: incremental check (only the changed region), split
   into sub-models checked separately, parallel checks. Acceptance: all intermediate states of Duo checked
   within the limit, or documented why not.
4. **PDF size for large closed bodies.** Texture cube: 23 MB. Target < 10 MB via image downsampling or vector
   rendering for simple steps.
5. **Estimate quality in `inspect`.** Thin large plates are underestimated (castle: 602 estimated, 1,651 actual).
   Add a plate-aware term; acceptance: 15 of 15 test runs inside the shown range.
6. **Feedback scale documented** in `--help` and README (1–5 stars, 5 = best).
7. Housekeeping: trimesh bug report (owner submits), optional release pages for v0.0.0–v0.7.0.
8. **Slopes, fast: solver order and slopes back on (moved up from 2.0, product owner 2026-11-07).** The
   "HiGHS hang" with slopes is solved by the order of the LP attempts, not by new placement code: on slope
   layouts simplex presolve stalls (upstream #88) while the interior-point method without crossover solves
   the same LPs in under a second (bunny, 16 studs, slopes: 147 s → 17.5 s with it first; docs/benchmarks.md,
   "Slopes on the new path"). Change the order to "simplex 1 s, then interior point without crossover, then
   the 1.2 chain"; the 5 s cap per attempt stays. Acceptance: small models are not noticeably slower than in
   1.2; slopes are on by default only if every fixture stays one stable piece and needs at most twice the time
   without slopes; slopes are drawn as slopes in previews and PDFs. Placing *more* slopes stays in 2.0 (item 8
   there).

Order of work: 1 and 2 (done), then 8 (1.3.0), then 3–7.

---

## 2.0 – shape fidelity: from voxel stairs to a LEGO model

Goal: organic shapes (Duo's wings, the toadstool cap) look like LEGO designs, not voxel art.
Metric for every item: surface deviation to the input mesh (and part count) at unchanged stability.

8. **More slopes** (the 2.0 part of item 8; its speed part moved to 1.x as 1.3.0, which also removed the
   HiGHS hang). legolization's `preserve` mode only swaps exact profile matches and places few slopes at brick
   height (4 on 224 parts, 14 on 873). Pre-select slope candidates geometrically (outer edges with matching
   neighbour pattern) so more slopes are placed. Acceptance: deviation measurably lower at unchanged
   stability, bunny with slopes in < 2× the time without slopes.
9. **Tiles on surfaces meant to be smooth** (tops, bases, eyes). Rule: a top face that the input mesh renders
   flat and that no part sits on gets a tile instead of a plate.
10. **Curved parts** (arches, round bricks, round plates) at convex edges. Start with 1×1 round and 2×2 round;
    extend by benchmark.
11. **SNOT** (studs sideways) for vertical faces and thin wings. The biggest step: changes the voxel grid
    assumptions in `voxel/` and needs its own ADR before any code.
12. **Colour availability during placement** instead of splitting parts afterwards (depends on upstream #90/#91
    or our own catalogue-aware placer).
13. **`choose_part` with real content.** Once items 8–11 give alternatives, the LLM task picks by build
    ergonomics; validated against catalogue and stability as in Phase 7.

Order of work in 2.0 (product owner, 2026-11-10): **9, 8, 10, 11, 12, 13**. Tiles go first because they need no
change to legolization's placement and no upstream answer; the surface-deviation metric built for item 9 is the
baseline for 8, 10 and 11.
Product owner, 2026-11-11: item 9 shipped in 1.7.0 with tiles off by default (patchy on the castle). Before item 8
comes issue #44: a flat face is tiled only if at least 85 % of its open top can be tiled, otherwise the whole face
keeps its studs; if the castle and Duo pictures convince, tiles go on by default and the release becomes 2.0.0.
Product owner, 2026-11-11 (after #44): the 85 % rule left the castle and Duo without tiles, so issue #46 comes
next, still before item 8: parts reaching past the edge of a flat face are split there (inside plate + tile, outside
the brick stays) before the 85 % rule, at most +15 % parts per model. If the pictures convince, tiles go on by default
with splitting and 2.0.0; otherwise tiles go on with the 85 % rule only (also 2.0.0).

---

## 2.x – handling robustness and instructions

14. **Clutch-power heuristic** like Studio's hints (thin walls, cantilevers) in addition to the gravity check;
    report on the cover page, optionally auto-reinforce.
15. **Masonry offset.** 41 % of vertical joints run straight through to the next layer. Upstream candidate #11,
    or our own post-pass behind the `Placer` protocol once we own placement.
16. **Internal support for large hollow models** (pillars in the cavity, weight reduction).
17. **Geometric sub-assemblies**: detect symmetry and repeated modules ("build 2×"). Revisit here (product
    owner, 2026-11-09): whether models up to 500 parts should also use the checked layer order of 1.4
    instead of legolization's search (rocket: 0 instead of 11 steps that need a hand; STATUS has the
    commands to compare both PDFs).
18. **Automatic camera per step** to avoid hidden new parts.
19. **Cost estimate on the cover page** from BrickLink price data (catalogue already has the mapping).

---

## Later / undecided

- Interactive HTML viewer for instructions.
- Image-based LLM review: Claude looks at a rendered step page and rates clarity.
- Fine-tuning export once enough feedback exists.
- Simple local web UI (explicitly a non-goal in 1.0).
- Photo-to-mosaic mode (different product, same pipeline).
- Personal brick inventory as optional whitelist (needs an inventory first – separate project).
- Public gallery with an owner-designed Fusion model (owner's decision; Duo stays local).

---

## Working mode (unchanged from SPEC §8)

Vibe-coding: Claude Code decides technical questions and documents them as ADRs; the owner answers goal and
taste questions, at most three per session, each with a default. One PR per item, owner merges, tag per
release. Upstream first for anything generally useful; local patches are bridges, listed in docs/UPSTREAM.md.
