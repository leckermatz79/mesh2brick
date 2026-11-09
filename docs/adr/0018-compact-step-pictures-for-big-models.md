# 18. Compact step pictures for big models

- Status: accepted
- Date: 2026-11-09
- Refines: [ADR 0011](0011-own-instruction-layout.md) (own instruction layout)

## Context

Booklets of big closed bodies were 20–23 MB (textured cube 23.2 MB for 327 steps, STEP cube 20.4 MB,
castle 19.4 MB); ROADMAP item 4 asks for less than 10 MB. Legibility comes before file size, and the
look of the instructions is a product decision (two steps per page, yellow "first" boxes, blue
sub-assembly panels). Measured first (docs/benchmarks.md, "PDF size"): 85–95 % of a big booklet are
the step pictures, palette PNGs at 130 dpi. A picture's size follows the area the model covers, and
the bytes sit in its edges: joint lines and stud outlines, anti-aliased and quantized to 64 colours.

The levers, measured on single pictures and whole booklets:

- **Encoding (a):** a fast-octree palette instead of median cut gives 27–42 % smaller pictures; flat
  colours move by at most one level per channel, edges stay closer to the original. Other zlib
  strategies and PNG row filters gain at most 1.5 % over Pillow. Turning anti-aliasing off saves two
  thirds but makes edges jagged and joints heavier.
- **Resolution (b):** 110 dpi saves about a fifth, 100 dpi a third; a stud is still 17–20 pixels wide.
- **Vectors (c):** the same scene as PDF paths is 6–15 times bigger than the raster picture; vectors
  only win below about 120 polygons (one or two parts).
- **Simpler faded parts (d):** drawing the earlier (faded) parts without their joints halves a
  picture of a big model and lets the new parts stand out; dropping their studs as well removes what
  a builder counts positions on.

Encoding and resolution alone bring the cubes and the castle below 10 MB, but not the textured cube
(13.0 MB at 100 dpi): its two-colour pattern has many more edges. With (d) it is 9.6 MB at 110 dpi.

## Decision

- **Models above 500 parts get compact step pictures** (`render/pdf.py`, `compact_steps`): faded
  parts without joints (studs stay), a fast-octree palette and 110 dpi instead of 130. The product
  owner chose this variant on a comparison page (2026-11-09) and wants it for big models only; the
  boundary is the same as for checked layers (ADR 0017).
- **Small models keep the pictures of 1.4**, pixel for pixel; part tiles, callouts, cover and text
  are unchanged for every model. `PdfOptions.compact` can force either look.
- No vectors, no lower resolution than 110 dpi, anti-aliasing stays.
- `scripts/benchmark_release.py` reports kB per step and warns above 40 kB for models above 500
  parts (1.4: 43–75 kB, 1.5: 18–30 kB), so the size cannot grow back unnoticed; a unit test bounds a
  compact step picture of a synthetic 640-part block (20 kB; measured 11 kB, 33 kB uncompact).

## Consequences

- Every booklet of the fixtures is below 10 MB (textured cube 9.6 MB, the next 6.4 MB) and is written
  faster (textured cube 54 → 31 s), because fewer polygons are drawn.
- The step pictures of big models look different from 1.4: earlier parts are calm faces with studs,
  the new parts keep every joint. The gallery is unchanged (it shows small-model pages and models).
- The textured cube has the least margin (9.6 MB); a bigger closed body at 32 studs may need more,
  which the kB-per-step warning would show.
