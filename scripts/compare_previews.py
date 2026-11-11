# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Side-by-side previews of two release runs (e.g. without and with tiles).

    uv run python scripts/compare_previews.py out/release-1.5 out/tiles/flat \\
        --labels "1.6" "tiles" --out out/tiles/vorher-nachher [--only sphere_r10]

For every input converted in both runs, renders the finished models from the
same camera (``<name>.bricks.json``) next to each other, with part count,
tile count and surface deviation (if the run recorded it) under each, and
writes ``<name>.png``. ``--elevation`` / ``--azimuth`` change the view (a
steeper view shows tops better).
"""

from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path
from typing import Any

from benchmark_estimate import run_dir
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

from mesh2brick.model import BrickModel
from mesh2brick.render.preview import PreviewOptions, render_png

PANEL = (900, 700)


def _rows(results: Path) -> dict[str, dict[str, Any]]:
    """Rows by output folder name."""
    rows = json.loads((results / "results.json").read_text(encoding="utf-8"))
    return {run_dir(results, row).name: row for row in rows if not row["exit"]}


def _pairs(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Inputs in both runs: same folder, else same input (``--local`` adds -STUDS)."""
    pairs = {name: (before[name], after[name]) for name in before.keys() & after.keys()}

    def bare(name: str) -> str:
        return re.sub(r"-\d+$", "", name)

    rest = {bare(n): n for n in after if n not in pairs}
    for name in sorted(before.keys() - pairs.keys()):
        other = rest.get(bare(name))
        if other is not None and bare(name) not in pairs:
            pairs[bare(name)] = (before[name], after[other])
    return pairs


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """DejaVu Sans from matplotlib (has umlauts), else PIL's default."""
    try:
        path = font_manager.findfont("DejaVu Sans", fallback_to_default=True)
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size=size)


def _caption(label: str, model: BrickModel, row: dict[str, Any]) -> str:
    tiles = sum(1 for p in model.parts if p.category == "tile")
    text = f"{label}: {model.part_count:,} parts, {tiles} tiles"
    if deviation := row.get("deviation"):
        text += f", deviation {deviation['mean_mm']:.2f} / {deviation['p95_mm']:.2f} mm"
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--labels", nargs=2, default=("before", "after"))
    parser.add_argument("--out", type=Path, default=Path("out/compare"))
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--elevation", type=float, default=35.0)
    parser.add_argument("--azimuth", type=float, default=-60.0)
    args = parser.parse_args()
    pairs = _pairs(_rows(args.before), _rows(args.after))
    args.out.mkdir(parents=True, exist_ok=True)
    font = _font(20)
    options = PreviewOptions(
        width_px=PANEL[0],
        height_px=PANEL[1],
        elevation=args.elevation,
        azimuth=args.azimuth,
    )
    for name, (first, second) in sorted(pairs.items()):
        if args.only and name not in args.only:
            continue
        sheet = Image.new("RGB", (PANEL[0] * 2, PANEL[1] + 40), "white")
        draw = ImageDraw.Draw(sheet)
        for column, (label, row, results) in enumerate(
            (
                (args.labels[0], first, args.before),
                (args.labels[1], second, args.after),
            )
        ):
            folder = run_dir(results, row)
            model = BrickModel.load(next(folder.glob("*.bricks.json")))
            picture = Image.open(io.BytesIO(render_png(model, options)))
            sheet.paste(picture, (column * PANEL[0], 0))
            draw.text(
                (column * PANEL[0] + 12, PANEL[1] + 8),
                _caption(label, model, row),
                fill="black",
                font=font,
            )
        path = args.out / f"{name}.png"
        sheet.save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main()
