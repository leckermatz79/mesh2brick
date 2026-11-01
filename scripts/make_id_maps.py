# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Build src/mesh2brick/export/id_maps.json: LDraw -> BrickLink / Rebrickable IDs.

    uv run python scripts/make_id_maps.py

Covers every part legolization can place and every solid LDraw colour. A
mapping is only recorded when the source data confirms it (ADR 0005):

* colours -> BrickLink: exact (normalised) name match against BrickLink's
  colour guide; -> Rebrickable: same numeric ID *and* same name in
  Rebrickable's ``colors.csv``.
* parts: candidate numbers are the LDraw number and the number without a
  trailing variant letter (``3070b`` -> ``3070``). A candidate is accepted when
  the catalogue entry exists and its name has the same part type and
  dimensions as the LDraw description (``Tile 1 x 1 ...``).

Everything else is stored as ``null`` and shows up as "unverified" in BOMs.
Needs network access and the local LDraw library; runtime use is offline.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import html
import io
import json
import re
import time
import urllib.request
from pathlib import Path

from legolization.catalog import default_catalog

from mesh2brick.backends.legolization import color_info, solid_color_codes
from mesh2brick.backends.pyldraw import library_status

OUT = Path(__file__).resolve().parents[1] / "src/mesh2brick/export/id_maps.json"
BL_COLORS = "https://www.bricklink.com/catalogColors.asp"
BL_PART = "https://www.bricklink.com/v2/catalog/catalogitem.page?P={}"
RB_BASE = "https://cdn.rebrickable.com/media/downloads/"
AGENT = "mesh2brick-id-maps/0.1 (+https://github.com/leckermatz79/mesh2brick)"


def fetch(url: str) -> bytes:
    """GET ``url`` with an identifying user agent."""
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data: bytes = response.read()
    return data


def norm_color(name: str) -> str:
    """``Light_Bluish_Grey`` -> ``light bluish gray``."""
    text = name.replace("_", " ").lower().replace("grey", "gray")
    return " ".join(text.split())


PART_TYPES = ("slope", "tile", "plate", "dish", "brick")


def part_signature(name: str) -> tuple[str, str]:
    """(part type, dimensions) of a part name, e.g. ('slope', '45x2x2').

    The type is the most specific keyword present, so LDraw's "Slope Brick 45
    2 x 2", BrickLink's "Slope 45 2 x 2" and Rebrickable's "Brick Sloped 45°
    2 x 2" agree.
    """
    text = html.unescape(name).lower().lstrip("~=_ ").replace("sloped", "slope")
    words = set(re.findall(r"[a-z]+", text))
    kind = next((t for t in PART_TYPES if t in words), "")
    dims = "x".join(re.findall(r"\d+(?:\.\d+)?", text.split(" with ")[0])[:3])
    return (kind, dims)


def ldraw_description(library: Path, part: str) -> str:
    """First-line description of ``part``.dat in the LDraw library."""
    for root in (library / "ldraw" / "parts", library / "parts"):
        path = root / f"{part}.dat"
        if path.is_file():
            first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            return " ".join(first.removeprefix("0").split())
    msg = f"part {part} not found in the LDraw library"
    raise FileNotFoundError(msg)


def bricklink_colors() -> dict[str, int]:
    """Normalised BrickLink colour name -> BrickLink colour ID."""
    page = fetch(BL_COLORS).decode("utf-8", errors="replace")
    pairs = re.findall(
        r'fullWidth[^"]*">([^<]+)</span><span[^>]*idSection[^>]*>(.*?)</span>', page
    )
    result: dict[str, int] = {}
    for name, raw_id in pairs:
        ident = re.sub(r"<!--.*?-->|<[^>]+>", "", raw_id).strip()
        if ident.isdigit():
            result.setdefault(norm_color(html.unescape(name)), int(ident))
    if len(result) < 100:  # noqa: PLR2004 - the guide lists ~200 colours
        msg = f"BrickLink colour guide parse failed ({len(result)} colours)"
        raise RuntimeError(msg)
    return result


def rebrickable_csv(name: str) -> list[dict[str, str]]:
    """Rows of a Rebrickable CSV dump."""
    data = gzip.decompress(fetch(f"{RB_BASE}{name}.csv.gz")).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(data)))


def bricklink_part_name(number: str) -> str | None:
    """BrickLink catalogue name of a part number, or None if unknown."""
    page = fetch(BL_PART.format(number)).decode("utf-8", errors="replace")
    match = re.search(r"<title>(.*?)</title>", page, re.S)
    title = html.unescape(match.group(1)).strip() if match else ""
    if " : Part " not in title:
        return None
    return title.split(" : Part ")[0]


def candidates(part: str) -> list[str]:
    """LDraw number, then the number without a trailing variant letter."""
    stripped = re.sub(r"(?<=\d)[a-z]$", "", part)
    return [part] if stripped == part else [part, stripped]


def main() -> None:
    """Fetch the sources and write the JSON table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reuse-bricklink",
        action="store_true",
        help="take BrickLink IDs from the existing JSON instead of bricklink.com "
        "(BrickLink throttles repeated catalogue requests)",
    )
    args = parser.parse_args()
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    status = library_status()
    if status.library_path is None:
        msg = "LDraw library not configured"
        raise SystemExit(msg)
    parts = sorted({p.ldraw_part for p in default_catalog().parts.values()})
    print(f"{len(parts)} parts, fetching sources ...")
    if args.reuse_bricklink:
        bl_colors = {
            norm_color(str(row["name"])): int(row["bricklink"])
            for row in previous.get("colors", {}).values()
            if row.get("bricklink") is not None
        }
    else:
        bl_colors = bricklink_colors()
    rb_colors = {int(r["id"]): r["name"] for r in rebrickable_csv("colors")}
    rb_parts = {r["part_num"]: r["name"] for r in rebrickable_csv("parts")}

    colors: dict[str, dict[str, object]] = {}
    infos = color_info(solid_color_codes())
    for code, info in sorted(infos.items()):
        name = norm_color(info.name)
        rebrickable = (
            code if code in rb_colors and norm_color(rb_colors[code]) == name else None
        )
        colors[str(code)] = {
            "name": info.name.replace("_", " "),
            "bricklink": bl_colors.get(name),
            "rebrickable": rebrickable,
        }

    part_rows: dict[str, dict[str, object]] = {}
    for part in parts:
        description = ldraw_description(status.library_path, part)
        target = part
        if moved := re.match(r"~Moved to (\S+)", description):
            # LDraw alias file: map like the part it points to.
            target = moved.group(1)
            description = ldraw_description(status.library_path, target)
        signature = part_signature(description)
        rebrickable = next(
            (
                c
                for c in candidates(target)
                if c in rb_parts and part_signature(rb_parts[c]) == signature
            ),
            None,
        )
        bricklink = None
        if args.reuse_bricklink:
            known = previous.get("parts", {})
            bricklink = (known.get(target) or {}).get("bricklink") or (
                known.get(part) or {}
            ).get("bricklink")
        else:
            for candidate in candidates(target):
                name = bricklink_part_name(candidate)
                time.sleep(1.0)  # be polite to BrickLink
                if name is not None and part_signature(name) == signature:
                    bricklink = candidate
                    break
        part_rows[part] = {
            "description": description,
            "bricklink": bricklink,
            "rebrickable": rebrickable,
        }
        print(f"  {part:8s} {description[:40]:40s} BL={bricklink} RB={rebrickable}")

    OUT.write_text(
        json.dumps(
            {
                "schema": 1,
                "generated": dt.datetime.now(dt.UTC).date().isoformat(),
                "sources": {
                    "ldraw": "local LDraw library (part descriptions, colour names)",
                    "bricklink_colors": BL_COLORS,
                    "bricklink_parts": BL_PART,
                    "rebrickable": RB_BASE + "{colors,parts}.csv.gz",
                },
                "method": "see scripts/make_id_maps.py and docs/adr/0005",
                "colors": colors,
                "parts": part_rows,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    unmapped_colors = [c for c, v in colors.items() if v["bricklink"] is None]
    unmapped_parts = [p for p, v in part_rows.items() if v["bricklink"] is None]
    print(f"wrote {OUT}")
    print(f"colours without BrickLink ID: {len(unmapped_colors)} of {len(colors)}")
    print(f"parts without BrickLink ID: {unmapped_parts}")


if __name__ == "__main__":
    main()
