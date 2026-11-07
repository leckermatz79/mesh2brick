# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Build the example gallery (docs/gallery/) from a benchmark_release.py run.

    uv run python scripts/benchmark_release.py --out out/release
    uv run python scripts/make_gallery.py --results out/release

For every public example it writes ``docs/gallery/examples/<name>.png`` (the model
as read next to its voxels and its bricks) and the gallery page
``docs/gallery/README.md`` with the measured numbers. It also writes three overview
pictures: ``phase8-blender-rocket.png``, ``phase8-gallery.png`` (all brick models on
one sheet) and ``phase8-rocket-pdf.png`` (cover and a step page of the rocket
booklet). Only public models are used.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
PANEL = 420
SKIP = {"cube_10mm"}  # a plain cube; its numbers stay in the table
SHOWS = {
    "rocket": (
        "Blender file: materials, an Array modifier, a hidden helper, millimetre units",
        "Blender-Datei: Materialien, Array-Modifier, verstecktes Hilfsobjekt, mm",
    ),
    "toadstool": ("Material colours (OBJ)", "Materialfarben (OBJ)"),
    "bunny_lowpoly": (
        "Organic shape, thin ears, overlapping shells",
        "Organische Form, dünne Ohren, überlappende Hüllen",
    ),
    "vertex_colors": ("Vertex colours (PLY)", "Vertexfarben (PLY)"),
    "textured_cube": ("Image texture (OBJ)", "Bildtextur (OBJ)"),
    "two_bodies": ("STEP with two coloured bodies", "STEP mit zwei farbigen Körpern"),
    "castle": (
        "Generated STEP, about 1,650 parts: the v1.0 timing case",
        "Erzeugtes STEP, rund 1.650 Teile: der Zeit-Test für v1.0",
    ),
    "torus": ("Through-hole", "Durchgehendes Loch"),
    "l_bracket": ("Overhang", "Überhang"),
    "sphere_r10": ("Round shape", "Runde Form"),
    "heart": ("MagicaVoxel input (legolization example)", "MagicaVoxel-Eingabe"),
    "cube_10mm": ("Plain cube (STL and STEP twin)", "Würfel (STL und STEP)"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("out/release"))
    parser.add_argument("--docs", type=Path, default=ROOT / "docs" / "gallery")
    args = parser.parse_args()
    results: Path = args.results
    docs: Path = args.docs
    rows = [
        r
        for r in json.loads((results / "results.json").read_text())
        if r["public"] and not r["exit"]
    ]
    examples = docs / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    sheet: list[tuple[str, Image.Image]] = []
    for row in rows:
        name = _stem(row)
        if name in SKIP:
            continue
        source = _source(row, results)
        panels = _panels(source, results / name / f"{name}.bricks.json", name)
        _save(_join(panels), examples / f"{name}.png")
        sheet.append((name, panels[-1]))
        if name == "rocket":
            _save(_join(panels, size=520), docs / "phase8-blender-rocket.png")
            _pdf_pages(results / name / f"{name}.pdf", docs / "phase8-rocket-pdf.png")
    _save(_sheet(sheet), docs / "phase8-gallery.png")
    (docs / "README.md").write_text(_page(rows), encoding="utf-8")
    print(f"wrote {len(sheet)} examples to {examples}")


def _stem(row: dict[str, Any]) -> str:
    return str(row["label"]).split(" ")[0].rsplit(".", 1)[0]


def _source(row: dict[str, Any], results: Path) -> Path:
    label = str(row["label"]).split(" ")[0]
    return results / label if label == "castle.step" else FIXTURES / label


def _panels(source: Path, bricks: Path, name: str) -> list[Image.Image]:
    """Model as read (meshes only), voxels and bricks, each PANEL x PANEL."""
    from mesh2brick.backends.legolization import color_info  # noqa: PLC0415
    from mesh2brick.config import load_settings  # noqa: PLC0415
    from mesh2brick.inspection import inspect_file, render_inspection  # noqa: PLC0415
    from mesh2brick.model import BrickModel  # noqa: PLC0415
    from mesh2brick.render.preview import PreviewOptions, render_png  # noqa: PLC0415

    settings = load_settings(None, [])
    inspection = inspect_file(source, settings, name=name)
    colors = color_info(inspection.grid.colors_used)
    joined = Image.open(
        io.BytesIO(render_inspection(inspection, colors, panel_px=PANEL))
    ).convert("RGB")
    panels = [
        joined.crop((x, 0, x + PANEL, PANEL)) for x in range(0, joined.width, PANEL)
    ]
    model = BrickModel.load(bricks)
    title = f"bricks: {model.part_count:,} parts, {model.step_count} steps"
    brick_png = render_png(
        model, PreviewOptions(width_px=PANEL, height_px=PANEL, title=title)
    )
    panels.append(Image.open(io.BytesIO(brick_png)).convert("RGB"))
    return panels


def _join(panels: list[Image.Image], size: int = PANEL) -> Image.Image:
    scaled = [p.resize((size, size), Image.Resampling.LANCZOS) for p in panels]
    canvas = Image.new("RGB", (size * len(scaled), size), "white")
    for index, panel in enumerate(scaled):
        canvas.paste(panel, (index * size, 0))
    return canvas


def _sheet(items: list[tuple[str, Image.Image]], columns: int = 4) -> Image.Image:
    cell = 300
    rows = -(-len(items) // columns)
    canvas = Image.new("RGB", (columns * cell, rows * cell), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(font_manager.findfont("DejaVu Sans"), 18)
    for index, (name, panel) in enumerate(items):
        x, y = (index % columns) * cell, (index // columns) * cell
        # Drop the panel's own title strip and label it with the model name.
        body = panel.crop((0, int(panel.height * 0.09), panel.width, panel.height))
        body.thumbnail((cell, cell - 30), Image.Resampling.LANCZOS)
        canvas.paste(body, (x + (cell - body.width) // 2, y + 28))
        draw.text((x + cell // 2, y + 6), name, fill="black", font=font, anchor="mt")
    return canvas


def _pdf_pages(pdf: Path, target: Path) -> None:
    """Cover and the first step page of the booklet, side by side (pdftoppm)."""
    if shutil.which("pdftoppm") is None:
        print("pdftoppm missing (Homebrew: poppler); skipping the PDF picture")
        return
    pages: list[Image.Image] = []
    with tempfile.TemporaryDirectory() as tmp:
        for page in (1, 4):
            stem = Path(tmp) / f"p{page}"
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r",
                    "60",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-singlefile",
                    str(pdf),
                    str(stem),
                ],
                check=True,
            )
            pages.append(Image.open(f"{stem}.png").convert("RGB"))
    height = max(p.height for p in pages)
    canvas = Image.new("RGB", (sum(p.width for p in pages) + 20, height), "white")
    x = 0
    for page in pages:
        canvas.paste(page, (x, 0))
        x += page.width + 20
    _save(canvas, target)


def _save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(
        path, optimize=True
    )
    print(f"wrote {path} ({path.stat().st_size / 1e3:.0f} kB)")


INTRO = (
    "Every example model of the repository at the default size (longest axis 32",
    "studs), converted with the default settings: the model as mesh2brick reads it,",
    "its voxels and the placed bricks. Numbers from `scripts/benchmark_release.py` on",
    "an Apple M2 Max laptop (one conversion at a time).",
    "",
    "Jedes Beispielmodell des Repos in Standardgröße (längste Achse 32 Noppen) mit",
    "den Standardeinstellungen: das Modell, wie mesh2brick es einliest, seine Voxel",
    "und die gesetzten Steine. Zahlen aus `scripts/benchmark_release.py` auf einem",
    "Apple-M2-Max-Laptop (eine Umwandlung nach der anderen).",
)


def _page(rows: list[dict[str, Any]]) -> str:
    lines = [
        "<!-- Generated by scripts/make_gallery.py; edit the script. -->",
        "# Beispielgalerie · Example gallery",
        "",
        *INTRO,
        "",
        "![All examples](phase8-gallery.png)",
        "",
        "| Model | Shows · zeigt | Parts | Steps | Colours | One stable piece | Time |",
        "|---|---|---:|---:|---:|---|---:|",
    ]
    for row in rows:
        name = _stem(row)
        english, german = SHOWS.get(name, ("", ""))
        stable = "yes · ja" if row["buildable"] else "no · nein"
        lines.append(
            f"| `{str(row['label']).split(' ')[0]}` | {english} · {german} "
            f"| {row['parts']:,} | {row['steps']} | {row['colours']} "
            f"| {stable} | {row['seconds']:.0f} s |"
        )
    lines.append("")
    for row in rows:
        name = _stem(row)
        if name in SKIP:
            continue
        english, german = SHOWS.get(name, ("", ""))
        lines += [
            f"## {name}",
            "",
            f"{english} · {german}",
            "",
            f"![{name}: as read, voxels, bricks](examples/{name}.png)",
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
