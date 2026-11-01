# 8. Colours from the model: visible surface, majority vote, common palette

- Status: accepted
- Date: 2026-11-01

## Context

SPEC Phase 3 asks for colour modes `vertex`, `texture` and `cad`, mapped to LDraw colour
codes. Real inputs differ a lot:

- 3D-printing projects (Bambu Studio, Orca, PrusaSlicer) assign a filament to each part.
  The first real model has 12 overlapping parts in 5 filament colours.
- CAD files (STEP, 3MF from Fusion) colour solids or faces.
- OBJ/PLY/glTF carry material colours, vertex colours or image textures.

Overlapping parts are the norm: pupils sit half inside the eye, the face covers the torso.
Colouring a cell by "any surface inside it" lets hidden surfaces vote. Thin details (a
coating thinner than half a cell) fill no cell at all, so their colour would vanish.

## Decision

**Sources.** Loaders deliver colours as `FaceColors`, arrays aligned with the faces. They
stay aligned through merging and mesh repair (dropped faces, filled holes, flipped winding):

- `cad`: one colour per face: 3MF base materials and colour groups, slicer filaments
  (they win over materials because they describe the actual print), STEP colours, and OBJ
  or glTF material colours.
- `vertex`: per-corner colours (vertex or face colour attributes), interpolated.
- `texture`: per-corner UVs and the image (glTF tint applied in linear light).

`color.mode` selects the most detailed source allowed: `cad` < `vertex` < `texture`; `auto`
(new default) uses whatever the file has. Each face uses its most detailed allowed source.
Surfaces without colour get `color.single_color`, and the result says so.

**Transfer to cells** (`voxel/color.py`):

1. Rays along x, y and z at the voxelizer's spacing (4 per stud) cross the mesh. Only
   crossings where the *union* of all parts begins or ends count, so hidden surfaces never
   vote. Where two bodies touch face to face, entering sorts before leaving, so the shared
   face is inside the union.
2. Each point belongs to the cell on the solid side of the surface. If that cell stayed
   empty (a coating thinner than half a cell), the point moves one cell further along its
   ray, so the coating colours the cell behind it.
3. The colour at the point (material, interpolated vertex colour or texel) is matched to
   the palette, and each cell takes the majority colour of its points. Ties go to the
   higher code (deterministic).
4. Cells without points copy the nearest coloured cell (Euclidean distance transform).

Colours are computed on the uncropped lattice, so points in empty border cells still count.

**Palette.** Matching uses legolization's metric (Oklab, chroma weighted ×3) through the
backend; we do not maintain our own colour distance. What changes is the set of colours it
may choose (`color.palette`):

- `common` (default): colours with confirmed BrickLink and Rebrickable numbers that LEGO
  produced in at least 1,000 different parts and within the last two years (Rebrickable's
  statistics, stored in `id_maps.json`). That is today's palette: 41 colours, Black to Coral.
- `solid`: every solid colour with both catalogue numbers.
- `all`: every solid LDraw colour (legolization's palette).

Metallic-looking finishes (Flat Silver, which BrickLink files under "Pearl", plus gold and
copper tones) are excluded from `common` and `solid` (SPEC §2: metallics only on opt-in).

## Consequences

- The first real model comes out in its real filament colours: white, green, black, orange
  and lime, 1,013 parts in about 2 minutes, stable.
- Without the `common` palette, its orange matched "Warm Yellowish Orange", a colour made in
  19 parts in 2004 that could hardly be bought.
- Pure sRGB primaries can land on neighbouring colours (#FF0000 → Reddish Orange), because
  LDraw's Red (#B40000) is much darker. Real filament and CAD reds land on Red.
- Renamed colours are missing from `common` until Phase 4 builds a full cross-reference via
  Rebrickable. Example: LDraw "Medium Lilac" is BrickLink/Rebrickable "Dark Purple".
- Not yet read: 3MF textures and multi-material painting (both reported as notes).
