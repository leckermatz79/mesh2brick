# 4. Placement receives the solid grid; the backend hollows it

- Status: accepted
- Date: 2026-11-01

## Context

`voxel.fill: hollow` saves parts by building only a shell. Hollowing is a simple erosion,
but a hollow shell can be unstable (for example a thin roof over a large void).
legolization's pipeline hollows the grid itself. When the stability check finds weak
bricks, it puts material back into exactly those columns ("hollow restore") and re-places.
That only works if legolization knows the original, solid grid.

## Decision

`voxelize` always produces the **solid** grid. With `fill: hollow` the backend adapter
passes the solid grid together with `hollow=True` and the shell thickness
(`wall_thickness` studs horizontally, `wall_thickness` × cell height in plates vertically).
Our own erosion (`voxel.voxelize.hollow`) stays available for previews and material
estimates (`voxelize` prints "~N of M cells to build"). It is never used to feed
placement.

## Consequences

- Stability-driven restoring works as designed; the user sees one consistent setting.
- The cell estimate printed by `voxelize` is approximate, because legolization's shell rule
  and the restore loop can differ slightly from our erosion.
- If another backend without hollowing is added later, its adapter must hollow with
  `voxel.voxelize.hollow` itself.
