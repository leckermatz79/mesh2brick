# 5. BrickLink/Rebrickable numbers only from confirmed sources

- Status: accepted
- Date: 2026-11-01

## Context

Models use LDraw part and colour numbers. BrickLink and Rebrickable, where people buy and
manage parts, partly use different numbers: LDraw red `4` is BrickLink `5`, LDraw tile
`3070b` is BrickLink `3070`. The `rebrickable` package resolves LDraw IDs reliably only
through Rebrickable's online API (it needs an API key) or by colour-value similarity offline.
SPEC §2 forbids guessing IDs.

## Decision

`scripts/make_id_maps.py` builds a translation table once, and it is committed as
`src/mesh2brick/export/id_maps.json` (with sources and date), so conversion stays offline. It
covers every part legolization can place (52) and every solid LDraw colour (111). A mapping is
recorded only when the source confirms it:

- **Colours → BrickLink:** exact name match against BrickLink's colour guide.
- **Colours → Rebrickable:** the same number *and* the same name in Rebrickable's `colors.csv`.
- **Parts:** the LDraw number, or the same number without its variant letter, must exist in
  the catalogue, with the same part type and dimensions in its name.

Everything else is `null`. The BOM keeps such lines in mesh2brick's own CSV, lists them as
comments in the BrickLink XML, and reports them as warnings. Nothing is silently dropped or
guessed.

## Consequences

- All 52 placeable parts and 93 of 111 colours have confirmed BrickLink and Rebrickable
  numbers. The 18 unconfirmed colours are exotic (inks, "Conductive Black", Fabuland). BOMs
  can still contain them if a model uses them, and then they are flagged.
- BrickLink throttles repeated catalogue requests. `--reuse-bricklink` regenerates the table
  from the BrickLink values already stored.
- Phase 4 (catalogue) replaces or extends the table when the part catalogue grows beyond
  legolization's parts. The method stays the same.
