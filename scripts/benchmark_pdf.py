# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Where the bytes of an instruction PDF are (Roadmap 4).

    uv run python scripts/benchmark_pdf.py out/release-1.4/cube/cube.bricks.json ... \\
        [--out out/pdf-size] [--json results.json] [--set NAME=VALUE] [--dpi 110]

Each input is a ``.bricks.json`` written by ``convert``; the booklet is
written again (placement is not repeated) while every picture the booklet
renders is counted by kind: step pictures, part tiles of the parts list and
the callouts, callouts of attached sub-assemblies and pre-assemblies, the
cover picture. What remains of the file is page content (text, vectors),
fonts and PDF structure. Per step picture it also records the share of
non-background pixels and the number of visible and new parts, to see what
a picture's size depends on. ``--compact on|off`` forces or prevents the
compact step pictures of ADR 0018 (default: by model size), ``--dpi`` sets
the step-picture resolution, and ``--set`` changes a module constant of
``mesh2brick.render.preview``/``pdf`` for the run.
"""

from __future__ import annotations

import argparse
import io
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("out/pdf-size"))
    parser.add_argument("--json", type=Path)
    parser.add_argument("--set", action="append", default=[], dest="overrides")
    parser.add_argument("--tag", default="", help="suffix for the PDF names")
    parser.add_argument("--dpi", type=float, default=None, help="step picture dpi")
    parser.add_argument(
        "--compact",
        choices=("auto", "on", "off"),
        default="auto",
        help="compact step pictures (ADR 0018); auto decides by model size",
    )
    args = parser.parse_args()
    rows = [
        _measure(path, args.out, args.overrides, args.tag, args.dpi, args.compact)
        for path in args.inputs
    ]
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    _print_table(rows)


def _apply(overrides: list[str]) -> None:
    from mesh2brick.render import pdf, preview  # noqa: PLC0415

    for item in overrides:
        name, _, value = item.partition("=")
        module = pdf if hasattr(pdf, name) else preview
        current = getattr(module, name)
        setattr(module, name, type(current)(json.loads(value)))


def _measure(  # noqa: PLR0917 - one run's settings
    path: Path,
    out: Path,
    overrides: list[str],
    tag: str,
    dpi: float | None,
    compact: str,
) -> dict[str, Any]:
    from mesh2brick.export.bom import build_bom  # noqa: PLC0415
    from mesh2brick.model import BrickModel  # noqa: PLC0415
    from mesh2brick.render import pdf  # noqa: PLC0415
    from mesh2brick.render.preview import step_view  # noqa: PLC0415

    _apply(overrides)
    forced = {"auto": None, "on": True, "off": False}[compact]
    model = BrickModel.load(path)
    counted: dict[str, list[int]] = defaultdict(list)
    steps: list[dict[str, Any]] = []

    def wrap(name: str, kind: str) -> Any:
        original = getattr(pdf, name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            pictures = result if isinstance(result, list) else [result]
            counted[kind].extend(len(p) for p in pictures)
            if kind == "steps":
                for index, png in enumerate(pictures):
                    visible, new = step_view(model, index)
                    steps.append(
                        {
                            "bytes": len(png),
                            "fill": _fill(png),
                            "visible": len(visible),
                            "new": len(new),
                        }
                    )
            return result

        setattr(pdf, name, wrapped)
        return original

    originals = {
        name: wrap(name, kind)
        for name, kind in (
            ("render_step_images", "steps"),
            ("render_part_png", "part tiles"),
            ("render_parts_png", "callouts"),
            ("render_png", "cover"),
        )
    }
    target = out / f"{model.name}{tag}.pdf"
    started = time.perf_counter()
    try:
        report = pdf.write_instructions(
            model,
            build_bom(model),
            target,
            pdf.PdfOptions(
                language="de",
                compact=forced,
                **({} if dpi is None else {"dpi": dpi}),
            ),
        )
    finally:
        for name, original in originals.items():
            setattr(pdf, name, original)
    seconds = time.perf_counter() - started
    total = target.stat().st_size
    pictures = {kind: sum(sizes) for kind, sizes in counted.items()}
    row = {
        "model": model.name,
        "parts": model.part_count,
        "steps": model.step_count,
        "pages": report.pages,
        "pdf_bytes": total,
        "seconds": round(seconds, 1),
        "pictures": pictures,
        "picture_counts": {kind: len(sizes) for kind, sizes in counted.items()},
        "rest": total - sum(pictures.values()),
        "step_pictures": steps,
        "overrides": overrides,
        "dpi": dpi,
        "compact": pdf.compact_steps(
            model,
            pdf.PdfOptions(compact={"auto": None, "on": True, "off": False}[compact]),
        ),
    }
    print(
        json.dumps({k: v for k, v in row.items() if k != "step_pictures"}), flush=True
    )
    return row


def _fill(png: bytes) -> float:
    """Share of pixels that differ from the corner (background) colour."""
    with Image.open(io.BytesIO(png)) as image:
        pixels = np.asarray(image.convert("RGB"))
    return float((pixels != pixels[0, 0]).any(axis=2).mean())


def _print_table(rows: list[dict[str, Any]]) -> None:
    print()
    print(
        "| Model | Parts | Steps | PDF MB | Step pictures MB | kB per step "
        "| Part tiles MB | Callouts MB | Cover MB | Rest MB | Time s |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        p = r["pictures"]
        mb = lambda v: f"{v / 1e6:.2f}"  # noqa: E731
        print(
            f"| {r['model']} | {r['parts']:,} | {r['steps']} | {mb(r['pdf_bytes'])} "
            f"| {mb(p.get('steps', 0))} | {p.get('steps', 0) / r['steps'] / 1e3:.1f} "
            f"| {mb(p.get('part tiles', 0))} | {mb(p.get('callouts', 0))} "
            f"| {mb(p.get('cover', 0))} | {mb(r['rest'])} | {r['seconds']} |"
        )


if __name__ == "__main__":
    main()
