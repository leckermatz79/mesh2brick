# 9. Part catalogue from LDraw geometry, offline Rebrickable data, whitelist via the backend

- Status: accepted
- Date: 2026-11-01

## Context

SPEC Phase 4 asks for three things:

- `PartSpec` derived from pyldraw3 geometry (brick/plate/slope/tile) with a JSON cache.
- An offline Rebrickable catalogue for names, availability and the BrickLink mapping.
- Whitelists/blacklists from the configuration passed to legolization, with an upstream
  PR if legolization does not support them.

Acceptance: `mesh2brick catalog list --category slope` works offline, and the BOM shows
Rebrickable names.

Findings (legolization 0.5.0, rebrickable 1.1.0, pyldraw3 1.7.0):

- legolization places 29 parts: 11 bricks, 11 plates, 4 tiles and 3 slopes. Its other 26
  catalogue entries only serve LDraw import.
- `legolization.run()` always uses `default_catalog()`, and `PipelineConfig` has no
  catalogue or part filter.
- Experiments with every single part removed, and with ten random subsets per height unit:
  - legolization needs the 1 x 1 brick (3005) and plate (3024) by name (`KeyError`).
  - With slopes on, it needs all three slopes by name.
  - Any other subset places correctly and never uses an excluded part.
- The `rebrickable` package builds its offline catalogue as an SQLite database from all CSV
  dumps. That includes the inventories (the `inventory_parts` dump alone is 14 MB
  compressed). Its API is asynchronous, and BrickLink numbers need the online API with a key.
- Rebrickable's `elements.csv` (1.1 MB) lists every part/colour pair LEGO issued.
- pyldraw3's `part_bounding_box` and `part_studs` resolve a part's subfile tree in
  milliseconds.

## Decision

**Part specs** (`catalog/parts.py`): the backend reports a part's bounding box and upward
studs; `derive_spec` turns them into footprint (studs), height (plates), top studs and a
category from the LDraw description ("Tile", "Slope", "Plate" without studs = tile). Specs
are cached as JSON per LDraw release in the user cache directory (`platformdirs`,
overridable with `MESH2BRICK_CACHE_DIR`). A test checks every placeable part against
legolization's own cell model: all 29 agree in footprint, height and category.

**Offline catalogue data** (`catalog/rebrickable.py`, `catalog/id_maps.json`): instead of
the `rebrickable` package's database, `scripts/make_id_maps.py` extends the table of ADR
0005 at generation time:

- Rebrickable part names.
- The LDraw colours each part is produced in, from `elements.csv`. A part without any
  element data counts as "unknown", not "made in no colour".
- Renamed colours, matched in two confirmed steps:
  1. The same ID with a near-identical RGB value. Rebrickable kept LDraw's old numbers:
     LDraw 85 "Medium Lilac" is Rebrickable 85 "Dark Purple".
  2. BrickLink's colour with Rebrickable's name.
- Every colour mapping records how it was found (`match`).

The table ships with mesh2brick. Runtime needs no network, no download and no API key. The
`rebrickable` package stays a dependency for its parsers (BOM cross-checks in the tests).

**Whitelist** (`catalog/whitelist.py`):

- `parts.categories` picks families, `parts.include` narrows them, `parts.exclude` removes
  parts.
- The backend states its rules (`BackendRules`: required 3005/3024, slopes coupled).
  Impossible settings are rejected with a clear message:
  - an unknown number,
  - a part the backend cannot place,
  - an included part from a disabled family,
  - an excluded filler part,
  - a partly excluded slope group.
- An include list without the fillers gets them added, with a note.
- The adapter hands the resulting part set to legolization through a scoped local patch:
  `legolization.pipeline.default_catalog` returns the filtered catalogue during `run()` and
  is restored afterwards. Import-only entries stay untouched. An upstream PR draft adds a
  catalogue option to `PipelineConfig` (docs/UPSTREAM.md #8); it will be opened only after
  the product owner approves.

**CLI** (`catalog list [--category] [--all] [--json]`, `catalog show PART`): sizes from
the local LDraw library, names, numbers and colours from the bundled table, and whether
the current settings allow each part. `--all` adds other LDraw parts of a family from
`parts.lst` (descriptions only, printed variants left out).

## Consequences

- Both acceptance criteria hold offline. A test blocks sockets during `catalog list`.
- Parts lists show Rebrickable names and flag part/colour pairs LEGO never produced. They
  are only flagged; placement does not avoid them yet.
- The default `common` palette gains Dark Purple through the colour cross-reference.
- Narrow whitelists cost parts and time: the bunny at 20 studs with only 2x4, 2x2 and 1x2
  bricks needs 356 instead of 177 parts and 85 instead of 5 seconds.
- The local patch must be revisited on every legolization upgrade (a test checks that it is
  undone even when placement fails).
