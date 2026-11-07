# 11. Own PDF instruction layout with reportlab

- Status: accepted
- Date: 2026-11-07

## Context

SPEC §1 asks for a PDF with a cover (picture, part count, dimensions), parts-list pages,
step pages with part call-outs, faded earlier steps, 1–4 steps per page, German and
English. SPEC Phase 6: "own PDF layout if the legolization PDF is not enough".

Phases 2–5 used legolization's booklet with our own step pictures. The gap list in
docs/STATUS.md shows what it cannot do:

- no model picture and no size in centimetres on the cover,
- internal part keys (`brick_2x4`) instead of names, and no part pictures,
- call-outs as text,
- English only (its text is hard-coded),
- technical warnings ("prefix unstable (score 1.00)"),
- fonts not embedded (some viewers show no text),
- fixed 2 steps per page.

None of this can be configured, and changing the layout upstream would mean redesigning
legolization's booklet for one consumer.

## Decision

mesh2brick draws its own booklet (`render/pdf.py`) from the backend-neutral `BrickModel`:

- **Library: reportlab** (BSD). legolization already depends on it, so nothing new is
  installed. WeasyPrint would need system libraries (Pango, cairo) and HTML/CSS
  for a layout that is mostly placed pictures.
- **Pictures:** our own renderer (`render/preview.py`) for steps, parts, sub-assemblies and
  pre-assemblies, as before. Part pictures share one scale (small parts are enlarged to at
  least 55 % of the largest part so a 1 x 1 plate stays recognisable). Step pictures grow
  with the model instead of always showing the finished model's frame.
- **Small files:** the palette PNGs are embedded as they are (Flate with PNG predictors),
  not re-encoded by reportlab, which would double their size. This uses reportlab's
  internal image API; the fallback for other PNGs is the public `drawImage`, and tests
  cover both paths.
- **Fonts:** DejaVu Sans from matplotlib's data folder is embedded as a subset (umlauts,
  `×`), so every viewer shows the text.
- **Language:** all text lives in `render/text.py` (German and English), written for
  builders. German part names are built from family and size (`Stein 2 × 4`); English uses
  Rebrickable's names. Colour names stay the catalogue names in both languages, so they
  match BrickLink and Rebrickable shops.
- **Hints:** per-step verdicts in the model (`BuildStep.stable`, `fragile`, `PlacedPart.unit`)
  become plain sentences ("hold the model with one hand here"). Layer-order plans get one
  note on the cover instead of a warning on every step.
- The backend's `write_instructions` (legolization booklet) is removed.

## Consequences

- Every gap in the list is closed, and the booklet no longer depends on the backend; a
  `.bricks.json` (schema 2) holds everything it needs.
- New config option `output.steps_per_page` (1–4, default 2); `output.language` now
  takes effect.
- The bunny at 32 studs (873 parts, 125 steps) gives a 65-page, ~5.5 MB PDF in ~15 s.
- Slopes are still drawn as their bounding boxes (renderer limitation, as before).
- The raw-PNG embedding relies on reportlab internals (`Canvas._doc`, `_setXObjects`,
  `_code`); a reportlab upgrade that changes them fails the PDF tests, not silently.
