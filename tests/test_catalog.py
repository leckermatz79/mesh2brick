# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Part catalogue (SPEC Phase 4): specs, cache, whitelist, listing, Rebrickable data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mesh2brick.catalog.listing import catalog_rows, library_rows, spec_row
from mesh2brick.catalog.parts import (
    PartGeometry,
    PartSpec,
    category_of,
    clean_description,
    derive_spec,
    load_cache,
    nominal_size,
    part_specs,
    save_cache,
    spec_cache_path,
)
from mesh2brick.catalog.rebrickable import (
    available_colors,
    color_name,
    common_colors,
    load_id_maps,
    part_name,
)
from mesh2brick.catalog.whitelist import (
    BackendRules,
    PlaceablePart,
    WhitelistError,
    allowed_parts,
)
from mesh2brick.config import PartsConfig


def geometry(
    part: str,
    description: str,
    size: tuple[float, float, float],
    studs: int,
) -> PartGeometry:
    """Bounding box like LDraw's: centred in x/z, body from y=0 down to +y."""
    x, z, height = size
    return PartGeometry(
        part=part,
        description=description,
        min_ldu=(-x / 2, -4.0 if studs else 0.0, -z / 2),
        max_ldu=(x / 2, height, z / 2),
        top_studs=studs,
    )


# ------------------------------------------------------------------ specs
@pytest.mark.parametrize(
    ("geo", "category", "size"),
    [
        (
            geometry("3001", "Brick  2 x  4", (80, 40, 24), 8),
            "brick",
            "2 x 4 x 1 brick",
        ),
        (geometry("3024", "Plate  1 x  1", (20, 20, 8), 1), "plate", "1 x 1 x 1 plate"),
        (
            geometry("3070b", "Tile  1 x  1 with Groove", (20, 20, 8), 0),
            "tile",
            "1 x 1 x 1 plate",
        ),
        (
            geometry("x", "Plate  2 x  2 without Studs", (40, 40, 8), 0),
            "tile",
            "2 x 2 x 1 plate",
        ),
        (
            geometry("3039", "Slope Brick 45  2 x  2", (40, 40, 24), 2),
            "slope",
            "2 x 2 x 1 brick",
        ),
        (
            geometry("2454", "Brick  1 x  2 x  5", (20, 40, 120), 2),
            "brick",
            "1 x 2 x 5 bricks",
        ),
        (
            geometry("3062", "Round Brick 1 x 1", (20, 20, 24), 1),
            "other",
            "1 x 1 x 1 brick",
        ),
        (
            geometry("y", "Plate  2 x  2 x 2/3", (40, 40, 16), 4),
            "plate",
            "2 x 2 x 2 plates",
        ),
    ],
)
def test_derive_spec(geo: PartGeometry, category: str, size: str) -> None:
    spec = derive_spec(geo)
    assert spec.category == category
    assert spec.size == size
    assert spec.width <= spec.length
    assert spec.top_studs == geo.top_studs


def test_description_helpers() -> None:
    assert clean_description("~Brick  2 x  4") == "Brick 2 x 4"
    assert nominal_size("Plate  8 x  2") == (2, 8)
    assert nominal_size("Minifig Head") is None
    assert category_of("=Slope Brick 33 3 x 1", 1) == "slope"
    assert category_of("Brick  1 x  1", 1) == "brick"


def test_spec_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def source(part: str) -> PartGeometry:
        calls.append(part)
        return geometry(part, "Brick  1 x  2", (20, 40, 24), 2)

    cache = spec_cache_path(tmp_path, "2610")
    first = part_specs(["3004", "3004", "3010"], source, cache=cache, release="2610")
    assert calls == ["3004", "3010"]
    assert set(first) == {"3004", "3010"}
    again = part_specs(["3004", "3010"], source, cache=cache, release="2610")
    assert calls == ["3004", "3010"]  # served from the cache
    assert again == first
    part_specs(["3004"], source, cache=cache, release="2611")  # new library release
    assert calls == ["3004", "3010", "3004"]
    cache.write_text("{broken", encoding="utf-8")
    assert load_cache(cache, "2611") == {}
    assert part_specs(["3004"], source)["3004"].size == "1 x 2 x 1 brick"


def test_cache_file_format(tmp_path: Path) -> None:
    spec = PartSpec("3001", "Brick 2 x 4", "brick", 2, 4, 3, 8)
    path = tmp_path / "sub" / "specs.json"
    save_cache(path, "2610", {"3001": spec})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["release"] == "2610"
    assert load_cache(path, "2610") == {"3001": spec}
    assert load_cache(path, "other") == {}
    assert spec_cache_path(tmp_path, "rel/../x").name == "partspecs-rel_.._x.json"


# ------------------------------------------------------------------ whitelist
PLACEABLE = (
    PlaceablePart("3005", "brick"),
    PlaceablePart("3001", "brick"),
    PlaceablePart("3024", "plate"),
    PlaceablePart("3023", "plate"),
    PlaceablePart("3070b", "tile"),
    PlaceablePart("3039", "slope"),
    PlaceablePart("3040b", "slope"),
)
RULES = BackendRules(
    required=frozenset({"3005", "3024"}),
    coupled=(frozenset({"3039", "3040b"}),),
    reasons={"3005": "filler", "3024": "filler", "3039": "slope pass"},
)


def allow(**settings: object) -> frozenset[str]:
    settings.setdefault("categories", ("brick", "plate"))  # the pre-1.3 default
    whitelist = allowed_parts(
        PLACEABLE,
        PartsConfig(**settings),  # type: ignore[arg-type]
        RULES,
        in_library=lambda part: part != "nope",
    )
    return whitelist.parts


def test_categories_pick_families() -> None:
    assert allow() == {"3005", "3001", "3024", "3023"}
    assert allow(categories=("brick", "plate", "tile")) == {
        "3005", "3001", "3024", "3023", "3070b",
    }  # fmt: skip


def test_include_and_exclude() -> None:
    assert allow(exclude=("3001",)) == {"3005", "3024", "3023"}
    whitelist = allowed_parts(
        PLACEABLE, PartsConfig(include=("3001",)), RULES, in_library=bool
    )
    assert whitelist.parts == {"3001", "3005", "3024"}
    assert "added 3005, 3024" in whitelist.notes[0]
    assert "filler" in whitelist.notes[0]
    assert whitelist.categories(PLACEABLE) == {"brick", "plate"}


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"exclude": ("3005",)}, "cannot remove 3005: filler"),
        ({"include": ("nope",)}, "unknown LDraw part"),
        ({"exclude": ("3062b",)}, "cannot place them"),
        ({"include": ("3070b",)}, "disabled categories tile"),
        (
            {"categories": ("brick", "plate", "slope"), "exclude": ("3039",)},
            "used together or not at all (slope pass); missing: 3039",
        ),
    ],
)
def test_impossible_settings(settings: dict[str, object], message: str) -> None:
    with pytest.raises(
        WhitelistError, match=message.replace("(", r"\(").replace(")", r"\)")
    ):
        allow(**settings)


def test_coupled_group_can_go_completely() -> None:
    parts = allow(categories=("brick", "plate", "slope"), exclude=("3039", "3040b"))
    assert not parts & {"3039", "3040b"}
    assert allow(categories=("brick", "plate", "slope")) >= {"3039", "3040b"}


# ------------------------------------------------------------------ listing
def test_catalog_rows_and_json() -> None:
    specs = {
        "3001": PartSpec("3001", "Brick 2 x 4", "brick", 2, 4, 3, 8),
        "3005": PartSpec("3005", "Brick 1 x 1", "brick", 1, 1, 3, 1),
        "3024": PartSpec("3024", "Plate 1 x 1", "plate", 1, 1, 1, 1),
    }
    rows = catalog_rows(specs, placeable=specs, allowed=frozenset({"3005"}))
    assert [r.part for r in rows] == ["3005", "3001", "3024"]
    assert [r.enabled for r in rows] == [True, False, False]
    assert rows[1].rebrickable_name == "Brick 2 x 4"
    assert rows[1].colors is not None
    assert 4 in rows[1].colors
    only = catalog_rows(specs, placeable=specs, allowed=None, category="plate")
    assert [(r.part, r.enabled) for r in only] == [("3024", None)]
    assert json.loads(json.dumps(rows[1].as_json()))["size"] == "2 x 4 x 1 brick"
    unknown = spec_row(
        PartSpec("x", "Foo", "other", 1, 1, 1, 0), placeable=False, enabled=False
    )
    assert unknown.colors is None
    assert unknown.bricklink is None


def test_library_rows_skip_variants() -> None:
    entries = [
        ("3001", "Brick  2 x  4"),
        ("3039", "Slope Brick 45  2 x  2"),
        ("3039p01", "Slope Brick 45  2 x  2 with Computer Pattern"),
        ("3039s01", "Slope Brick 45  2 x  2 with Stripe Sticker"),
        ("s/3001s01", "~Brick  2 x  4 without Front Face"),
        ("3622", "=Brick  1 x  3"),
        ("3626", "Minifig Head"),
    ]
    rows = library_rows(entries, skip=["3001"], category="slope")
    assert [(r.part, r.size, r.placeable) for r in rows] == [("3039", "2 x 2", False)]
    every = library_rows(entries)
    assert {r.part for r in every} == {"3001", "3039", "3626"}
    assert next(r for r in every if r.part == "3626").size == "-"


# ------------------------------------------------------------------ offline data
def test_rebrickable_data() -> None:
    assert part_name("3001") == "Brick 2 x 4"
    assert part_name("nope") is None
    colours = available_colors("3001")
    assert colours is not None
    assert {0, 4, 15} <= colours
    assert available_colors("nope") is None
    assert color_name(85) == "Medium Lilac"
    assert color_name(999_999) == "999999"
    assert 85 in common_colors()  # renamed colour now cross-referenced
    row = load_id_maps().colors[85]
    assert row["bricklink"] == 89  # BrickLink "Dark Purple"
    assert row["match"] == {"bricklink": "rebrickable name", "rebrickable": "id+rgb"}


def test_every_mapped_part_has_name_and_colours() -> None:
    maps = load_id_maps()
    for part, row in maps.parts.items():
        if row["rebrickable"] is not None:
            assert row["rebrickable_name"], part
            assert row["colors"] is None or row["colors"], part  # never "no colour"


# ------------------------------------------------------------------ library access
@pytest.mark.ldraw
def test_library_helpers() -> None:
    from mesh2brick.backends import BackendError  # noqa: PLC0415
    from mesh2brick.backends.pyldraw import (  # noqa: PLC0415
        describe,
        library_parts,
        library_release,
        part_exists,
        part_geometry,
    )

    assert library_release() not in {"", "unknown"}
    entries = dict(library_parts())
    assert " ".join(entries["3001"].split()) == "Brick 2 x 4"
    assert part_exists("3001")
    assert not part_exists("nope")
    assert describe("3023") == "Plate  1 x  2"  # "~Moved to 3023b" followed
    assert part_geometry("3023").top_studs == 2
    with pytest.raises(BackendError, match="nope"):
        part_geometry("nope")


def test_missing_library_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from mesh2brick.backends import BackendError, pyldraw  # noqa: PLC0415

    monkeypatch.setattr(
        pyldraw,
        "library_status",
        lambda: pyldraw.LibraryStatus(
            None, None, library_present=False, generated_present=False
        ),
    )
    with pytest.raises(BackendError, match="library is missing"):
        pyldraw.library_parts()
    assert pyldraw.library_release() == "unknown"
