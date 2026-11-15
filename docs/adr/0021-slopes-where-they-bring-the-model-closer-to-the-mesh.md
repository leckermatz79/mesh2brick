# 21. Slopes where they bring the model closer to the mesh: rated by the voxelizer, placed by an own pass

- Status: accepted
- Date: 2026-11-15
- Issue: #51 (ROADMAP item 8, the 2.0 part: "more slopes"; target release 2.1.0)

## Context

ROADMAP 8: legolization's `preserve` mode only swaps exact profile matches and adds nothing. In a
brick-height grid a slope's profile (full stud column, sloped column filled only in its bottom plate)
almost never matches the outside of the voxel shape, so 2.0.0 placed 130 slopes on the fixtures and
10 of them were visible: the rest sit on the inner wall of the hollow shell. Round shapes kept their
voxel stairs. The 2.0 metric (surface deviation to the input mesh, ADR 0020) is the acceptance
measure: slopes are good where the deviation drops, at unchanged stability. The product owner
(2026-11-15) asked for an own pass behind the `Placer` protocol, like the tile pass, without changes
to legolization, and allowed a slope to add material beyond the voxel shape where it lies closer to
the mesh than the stair.

**Measured first** (docs/benchmarks.md, "Slopes (ROADMAP 8)"): legolization's older `smooth` mode
(a 1 × 1 brick column at a descending stair becomes a 45° 2 × 1 slope) places 13–27 slopes per round
fixture, nearly all visible, at unchanged part count and stability, but the deviation does not drop
(sphere 2.05 → 2.06 mm, bunny 1.96 → 1.96 mm, rocket 1.46 → 1.48 mm). It looks only at the voxels: on half
of the stairs the mesh runs where the stair already is closer than the slope.

That measurement also exposed **two errors in the 2.0 metric**: (1) the sloped tops of slopes
always counted as outer surface, also those on the inner wall of a hollow model; they lie far from
the mesh, so the round fixtures read too high in 2.0.0 (sphere 2.35 instead of 2.05 mm). A sloped
top now counts when the cell above it is outside air. (2) A taller part right beside a sloped column
shows its side above the slope's face, but the slope's cells count as filled, so that face was in
neither the metric nor the preview (small white holes in previews of slope-rich models).
`render.preview.slope_gap_faces` now gives those faces, clipped per plate, to both. The 2.0.0 models
were measured again and are the baseline of this ADR; boxes, castle and Duo did not change.

**Why the stair is sometimes better.** A slope's face runs from the top of its stud column to a lip
of 4 LDU at the far edge: across the cell's diagonal. Where the mesh surface crosses a stair tread
near that diagonal, cutting the tread (or, when the tread is below, filling the corner above it) is
almost exact. Where it crosses the middle of tread and riser, the stair is closer: the slope would be
a quarter cell off. On a plane exactly one brick per stud every tread is in that position; on
rounded surfaces the position changes from stair to stair. Only the mesh can tell.

## Decision

1. **The voxelizer rates every possible slope while it still has the mesh** (`voxel/slopes.py`,
   stored as `VoxelGrid.slopes`, `float32[x, y, z, 4, 2]`, and in `.npz`). A candidate is a stud
   cell (filled), one of four descent directions and a kind: 45° with one sloped column (3040b, two
   side by side 3039) or 33° with two (4286). Each sloped column is a filled top cell (the slope cuts
   the stair's edge) or an empty cell on a filled one (the slope fills the corner, beyond the voxels).
   - **Tilt gate**: the up-facing mesh surface the vertical rays cross near the sloped columns
     tilts 15–85° (45°) or 8–60° (33°) and falls within 50° of the slope's direction. Flat faces
     (tiles) and level or vertical surfaces never get slopes; boxes get none, not even on a top the
     voxels overshoot.
   - **Gain**: along each of the 4 × 4 vertical rays of a sloped column (the voxelizer's rays) the
     length where bricks and mesh disagree, once for the stair (with its stud) and once for the
     slope's face; the gain is the difference, as a mean in LEGO mm over the sloped columns. For a
     gently curved surface the volume between bricks and mesh is the deviation integrated over the
     surface, so a positive gain means a lower surface deviation. Only positive gains are kept.
   - Watertight meshes only (inside and outside along a ray must be known), brick cells only, and
     only with `parts.slopes: mesh` and `slope` in `parts.categories`. Cost: 0.02–0.5 s.
2. **mesh2brick places the slopes itself, after legolization's run and the tiles, before the steps**
   (`backends/slopes.py`, `apply_slopes`, with the layout helpers it shares with the tile pass in
   `backends/layout_ops.py`; ordering in `place/slopes.py`; wiring in `backends/legolization.py`). Sites with a gain of
   at least 0.5 mm are tried best first (total gain; two 45° sites side by side also as one 3039,
   which ranks first). A slope takes a layer of three plates over its columns:
   - the bricks and plates under its stud columns and filled sloped columns are cut out; what is
     left of them becomes parts of the same family, height and colour (`rect_cover`), each resting on
     or under another part; afterwards such pieces are joined with neighbours of the same layer,
     height and colour into bigger parts where LEGO makes the result;
   - a sloped column on an empty cell must rest on a stud; nothing may rest on a sloped column; a
     cell taken by a tile, a slope placed before or a part reaching outside the three plates keeps
     the stair; the parts cut must share one colour;
   - **the model stays one piece**: the parts around the cut must still be connected, through the
     new parts or the long way round (breadth-first search); otherwise the stair stays;
   - **at most two parts more per slope** (the slope and the pieces, minus the parts cut): a slope
     in the middle of a long brick that would leave three pieces keeps the stair. Measured on the
     bunny: without the limit 140 slopes, +18.3 % parts, 1.76 / 4.10 mm; with it 129 slopes,
     +14.2 %, 1.78 / 4.13 mm (90 % of the gain for the +15 % guide of the tiles); at most one part:
     77 slopes, +5.4 %, 1.85 / 4.23 mm. The gain of a slope does not depend on its cost;
   - **colours one slope at a time**: a slope LEGO does not make in its colour (Rebrickable data)
     leaves the stair as it is, and the run counts such stairs per colour (handed over to ROADMAP 12).
     With `parts.availability: exclude`, legolization's placement still leaves out slopes missing in
     any model colour; this pass adds them back to the layout's catalogue and checks each colour
     itself (Duo and the textured cube get slopes where their colour exists).
3. **One stability check for tiles and slopes.** If a slope was placed or a tile made a part heavier,
   the whole model is checked in a thread while the steps are planned (as in ADR 0020; the thread was
   renamed `finish-check`). If it no longer holds together, the slopes are undone first; tiles that
   need a check are then checked alone if time allows (else undone too); the steps are planned again
   and the run says so. With too little time left for that check (the tile reserve), the slope pass
   is skipped: command line and cover page say "Slopes skipped: time limit; recommended
   --time 10min" (`BrickModel.slopes_skipped`, schema 7).
4. **Settings.** `parts.slopes: mesh` (default) is all of the above after legolization's `preserve`
   pass; `preserve` gives the 2.0.0 result; `smooth` is legolization's older pass (for comparison).
   The voxelizer computes the ratings only for `mesh`. `parts.slopes_max_share` (off by default)
   limits the slopes' extra parts per model, best slopes first (torus at +15 %: 84 instead of 169
   slopes, 1.74 instead of 1.66 mm; sphere 1.89 instead of 1.87 mm). Off, because the product owner
   set +15 % as a guide that is reported, not enforced, for the tiles; the question is in STATUS.
5. **Part estimate.** `inspect` adds 0.45 / 0.58 / 0.75 parts (low / expected / high) per stud cell
   with a slope worth placing (measured 0.49–0.71 on the release run); 15 of 15 runs inside the range.
6. **Display and export need nothing new** beyond the faces of fix (2): slopes are drawn as wedges since 1.3 in every turn
   (preview, step pictures, part tiles), the LDraw writer and the strict re-read handle all four
   turns of the three parts, the parts lists know 3039, 3040b and 4286. The release benchmark now
   records slopes and visible slopes per input (`fidelity.visible_parts`).

## Alternatives considered

- **legolization's `smooth` mode**: measured, no gain (see Context).
- **Sculpting the plate-level grid so `preserve` matches** (remove the upper two plates of a tread,
  add the bottom plate of a corner): uses legolization's own mechanism, but changes what its placer
  sees everywhere (different parts, time and stability on every model) and whether `preserve` then
  matches depends on its donor rule (at most 4 cells left over). The product owner asked for a
  post-pass; not pursued.
- **Classifying by tilt alone** ("45° here, 33° there"): half of the 45° stairs get worse (see
  Context). The tilt is only the gate; the gain decides.
- **A local hold rule as for tile cuts** (the parts around a cut must hang together through the new
  pieces alone): blocks 86 of 229 sites on the bunny; with "stays one piece" plus the stability check
  every fixture stays one stable piece with almost twice the slopes. Kept as the fast path.

## Consequences

- Measured on the release run (docs/benchmarks.md, "Slopes (ROADMAP 8)"): every run one stable piece;
  sphere 2.05 / 4.59 → 1.86 / 4.33 mm, bunny 1.96 / 4.40 → 1.78 / 4.12, toadstool 1.96 / 4.50 →
  1.75 / 4.20, torus 1.90 / 4.46 → 1.65 / 4.12, Duo at 32 studs 1.72 / 4.23 → 1.61 / 4.03; visible
  slopes 10 → 1,080 on the public fixtures (of 130 → 1,200 slopes); bunny 1.13 times its 2.0.0 time.

- Round shapes get visible slopes and come closer to their mesh; boxes, the castle and voxel files
  are unchanged (pixel-identical models).
- Slopes cost parts: cutting a brick for a slope usually leaves one or two pieces (about +1 part
  per slope after joining, at most +2 before); the run reports the increase against the +15 % guide
  of the tiles and takes nothing back for it.
- Inverted slopes (undersides of overhangs) and curved slopes are not in legolization's catalogue;
  the lower half of a sphere keeps its stairs (ROADMAP 10 / later).
- Upstream: nothing in this item depends on legolization; a slope pass driven by a mesh rating could
  be offered upstream later (docs/UPSTREAM.md).
