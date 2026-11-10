# 20. Tiles on flat tops: a mask from the mesh and an own pass after placement

- Status: accepted
- Date: 2026-11-10
- Issue: #42 (ROADMAP item 9, the first 2.0 item)

## Context

ROADMAP 9: "a top face that the input mesh renders flat and that no part sits on gets a tile instead
of a plate". The 2.0 metric is the surface deviation to the input mesh at unchanged stability; it did
not exist yet and was built first (`mesh2brick.fidelity`, docs/benchmarks.md "Shape fidelity
baseline").

legolization 0.5.0 already has `apply_tiles`, switched on through `tile` in `parts.categories`.
Measured on all fixtures (docs/benchmarks.md, "Tiles (ROADMAP 9)"):

- It tiles **every** open plate, wherever it is: 61–184 tiles on the level stairs of bunny, sphere,
  toadstool, torus and the vertex-colour sphere, which the product owner does not want by default.
- It never touches **bricks**. The tops of boxes are bricks (cubes, L-bracket, two bodies, the
  castle's walls and towers), so exactly the faces meant to be smooth kept their studs: 0 tiles on
  the cubes.
- It knows only four tile sizes (1 × 1, 1 × 2, 1 × 4, 2 × 2). The catalogue has 1 × 3, 1 × 6,
  1 × 8, 2 × 4 and 2 × 6 tiles with full geometry, but as import-only parts, so most plates
  (2 × 4, 1 × 6, 2 × 6 ...) kept their studs: the castle courtyard came out patchy.
- The deviation did not change on any model (within 0.01 mm), stability did not either.

## Decision

1. **The voxelizer marks flat tops while it still has the mesh** (`voxel/flat.py`, stored as
   `VoxelGrid.flat` and in `.npz`, together with the height of the face above the cell's top). Per top cell the 4 × 4 vertical rays of voxelization look for
   the up-facing surface closest to the cell's top. A cell is flat when all rays hit a face tilted
   at most 1° and their heights agree within 0.1 mm (LEGO scale); such cells form faces per layer,
   faces under 2 cells are dropped, and a neighbouring top cell joins its face when at least half of
   its rays hit that face at its height (faces rarely end on a stud line). Normals alone would also
   pass the pole of a fine dome; the height tolerance and "every ray" rule out curved tops. On the
   fixtures this marks the cube, L-bracket and two-bodies tops completely, the castle's courtyard,
   wall, tower and keep tops except partly covered border cells, Duo's base ring, and nothing on the
   sphere, bunny, torus, toadstool or rocket. Voxel files (`.vox`) have no mesh: every top counts.
2. **mesh2brick tiles itself, after legolization's run and before the steps**
   (`backends/legolization.py`, `apply_tiles`; arithmetic in `place/tiles.py`). legolization's own
   pass stays off (`PipelineConfig.tiles=False`). An open part (nothing on it) whose whole top layer
   lies in the mask gets a smooth top **where the face is**, rounded to a plate and at most one
   plate away from the voxel top:
   - face at the voxel top: a **plate** becomes a tile of the same size (part count unchanged),
     using all nine tile sizes of the catalogue (2 × 3 and 2 × 8 have none and become two tiles,
     only if each rests on something); a **brick** becomes **two plates of its size plus tiles**
     (+2 parts, more where the size needs two tiles: 2 × 8 → 2 × 2 × 4);
   - face a plate lower (the voxels rounded up): a brick becomes **one plate plus tiles** (+1);
     a plate stays at its height and becomes a tile;
   - face a plate higher (the voxels rounded down): **tiles are laid on** the brick or plate (+1);
   - only parts the whitelist allows and LEGO makes in the part's colour (Rebrickable data); else
     the studs stay. `parts.tiles_on_base: false` leaves the lowest brick layer alone,
     `parts.tiles: all` tiles every open top (the stairs too).
3. **Stability is checked again where a part got heavier** (two plates and a tile weigh about half
   as much again as the brick; a tile laid on a part adds its weight). The check of the whole model
   (legolization's analysis: 3 s for 189 parts, 14 s for 776, 33 s for 1,682, 65 s for 2,209) runs
   in a thread **while the steps are planned**: the planner spends that time waiting for its own
   worker processes. If the model no longer holds together, the tiles are undone and the steps are
   planned again (the run says so). With less time left before the export than 10 s + 0.02 s per
   part, only the changes that make parts lighter are made, and the run says how many tops keep
   their studs for lack of time; none when the run's own check did not finish.
   Where every change makes a part lighter on the same supports (plate → tile, brick → plate +
   tile), the run's verdict stands and nothing is checked: a lighter top on the same connections
   cannot make the model fall.
4. **No upstream dependency.** The pass needs nothing from legolization that 0.5.0 lacks, so the
   fork-or-wait question does not arise here. A general version (an optional cell mask for
   `apply_tiles`, bricks, the five import-only tiles as tiles) is upstream candidate #18; it would
   shrink our pass, the mask itself needs the mesh and stays here.

## Consequences

- See docs/benchmarks.md "Tiles (ROADMAP 9)" for the numbers per fixture: deviation, tiles, parts,
  stability and time against 1.6 and against legolization's pass.
- Parts: plates swapped for tiles do not change the count; a brick rebuilt one plate lower adds one
  part, at its height two, a tile laid on a part one (more where the size needs two tiles), shown per
  fixture and in the run's notes ("tiles on flat tops: ...").
- **Why the check runs beside the step planning** (the first version checked before it): Duo took
  164 s instead of 128 s and the castle had no time left for any intermediate state; in parallel Duo
  takes 138 s and the castle checks 135 of 236 states (1.6: 151 of 234).
- Without `tile` in `parts.categories` nothing changes against 1.6 (a test places the same model
  twice); the grid's mask is computed anyway (milliseconds) and stored.
- The new parts are ordinary parts afterwards: steps, PDF, LDraw and parts lists need nothing
  special. The preview draws tiles without studs (it did already); the PDF names them "Fliese" /
  Rebrickable's name; the LLM prompt says what a tile is.
- **Why "where the face is" and not always two plates + tile** (the first version): the cubes and
  the L-bracket are 26.7 bricks high, so their voxels end one plate above the mesh. Two plates + tile
  kept that plate: textured cube +359 parts (+16 %), 4 s over the time limit, PDF 10.3 MB (limit
  10 MB), no intermediate state checked; one plate + tile: +186 parts (+8 %), 244 s as in 1.6, 121
  states checked (1.6: 123), PDF 9.8 MB, and the top lies on the mesh's top.
- Plates do not go lower: where a flat face over plates lies a plate below the voxel top, the tiles
  stay at the voxel top. On the fixtures that never happens. Faces more than a plate away come one
  plate closer: only on the castle (32 of 375 tile cells), whose open STEP mesh is voxelized by
  "every cell the surface touches" and so stands up to a cell too high.
