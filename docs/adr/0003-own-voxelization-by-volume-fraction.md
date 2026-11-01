# 3. Own voxelization by volume fraction (column rasterization)

- Status: accepted
- Date: 2026-11-01

## Context

legolization can voxelize meshes itself: it marks every cell the surface touches and
floods the inside. SPEC Phase 1 asks for more: cells of one brick or one plate height,
occupancy decided by the **filled volume fraction** with a configurable threshold, a
documented rounding rule, and support for formats legolization does not read (3MF, later
STEP). Meshes can be large: the user's first real model has 2.1 million triangles in 12
overlapping parts.

## Decision

mesh2brick voxelizes meshes itself (`voxel/voxelize.py`). Each cell is sampled by 4 × 4
vertical rays. Along every ray we compute exactly where it is inside the model, using the
winding number of the surface crossings, which unions overlapping parts and keeps cavities
empty. The inside length is then split exactly into the cells. A cell counts as filled when
its average fill reaches `voxel.threshold` (default 0.5). All triangles are processed at once
with numpy, so Duo takes under a second. Rounding rule: each horizontal axis gets
`round_half_up(extent / pitch)` studs (at least 1) with the model centred on them, which keeps
symmetric models symmetric. Vertically the grid starts at the model's lowest point, so a flat
bottom lands exactly on a layer boundary. Meshes that stay open after repair fall back to
surface voxelization plus hole filling, with a warning. legolization's voxelizer remains the
reference in `docs/benchmarks.md`.

## Consequences

- Accuracy is measurable and good: the sphere at 32 studs deviates by less than 0.1 %
  in volume, a 10 mm cube becomes exactly one 1 × 1 brick.
- We own ~250 lines of geometry code. They are covered by analytic tests: half-filled
  cells, overlapping bodies, cavities, and chunking invariance.
- 3MF gets its own reader (standard library only), because generic loaders ignore the
  production extension that slicers such as Bambu Studio use.
