# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Words for the building instructions, in German and English.

All user-facing text of the PDF lives here, written for builders, not for
engineers: no stability scores, no solver names. Part names come from
Rebrickable in English; German names are built from the part's family and
size (``Stein 2 × 4``). Colour names are the catalogue names, so they can be
found in BrickLink and Rebrickable shops as written; German booklets add a
German name in brackets (``Bright Green (Hellgrün)``, product-owner decision
of 2026-11-07).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from mesh2brick.model import PlacedPart

Language = Literal["de", "en"]

_TEXT: Final[dict[str, dict[Language, str]]] = {
    "instructions": {"de": "Bauanleitung", "en": "Building instructions"},
    "parts": {"de": "Teile", "en": "Parts"},
    "steps": {"de": "Schritte", "en": "Steps"},
    "size": {"de": "Größe", "en": "Size"},
    "size_value": {
        "de": "{w} × {d} × {h} cm (B × T × H)",
        "en": "{w} × {d} × {h} cm (W × D × H)",
    },
    "weight": {"de": "Gewicht", "en": "Weight"},
    "weight_value": {"de": "ca. {value}", "en": "about {value}"},
    "colours": {"de": "Farben", "en": "Colours"},
    "stability": {"de": "Stabilität", "en": "Stability"},
    "sections": {"de": "Abschnitte", "en": "Sections"},
    "page_short": {"de": "S. {page}", "en": "p. {page}"},
    "stable_yes": {
        "de": "steht von allein, aus einem Stück",
        "en": "stands on its own, in one piece",
    },
    "stable_no": {
        "de": "hält laut Berechnung nicht von allein zusammen",
        "en": "does not hold together on its own by the calculation",
    },
    "stable_unknown": {"de": "nicht geprüft", "en": "not checked"},
    "parts_list": {"de": "Teileliste", "en": "Parts list"},
    "parts_list_total": {
        "de": "{parts} Teile in {lines} Sorten",
        "en": "{parts} parts of {lines} kinds",
    },
    "shopping": {
        "de": (
            "Zum Bestellen: Die Datei {bricklink} lässt sich bei BrickLink als "
            "Wunschliste hochladen, {rebrickable} bei Rebrickable als Teileliste."
        ),
        "en": (
            "To order: upload {bricklink} to BrickLink as a wanted list, or "
            "{rebrickable} to Rebrickable as a parts list."
        ),
    },
    "not_produced": {
        "de": (
            "LEGO stellt diese Teile nicht in dieser Farbe her. Ersetze sie z. B. "
            "durch zwei kürzere Teile derselben Farbe: {parts}"
        ),
        "en": (
            "LEGO does not make these parts in this colour. Replace them, for "
            "example, by two shorter parts of the same colour: {parts}"
        ),
    },
    "replacement": {
        "de": "Vorschlag: {part} statt {original}.",
        "en": "Suggestion: {part} instead of {original}.",
    },
    "step": {"de": "Schritt", "en": "Step"},
    "subassembly": {"de": "Baugruppe {name}", "en": "Sub-assembly {name}"},
    "subassembly_build": {
        "de": "Baugruppe {name} separat bauen",
        "en": "Build sub-assembly {name} separately",
    },
    "attach": {
        "de": "Baugruppe {name} aufsetzen",
        "en": "Attach sub-assembly {name}",
    },
    "hint_hold": {
        "de": "Halte das Modell hier mit einer Hand fest, bis es später Halt bekommt.",
        "en": "Hold the model with one hand here until a later step gives it support.",
    },
    "hint_hold_sub": {
        "de": "Halte die Baugruppe hier fest, bis sie später Halt bekommt.",
        "en": "Hold the sub-assembly here until a later step gives it support.",
    },
    "hint_hold_attach": {
        "de": "Halte die Baugruppe beim Aufsetzen fest, bis sie später Halt bekommt.",
        "en": "Hold the sub-assembly while attaching it until a later step holds it.",
    },
    "hint_fragile": {
        "de": "Neue Teile vorsichtig andrücken und das Modell dabei von unten stützen.",
        "en": "Press the new parts on gently and support the model from below.",
    },
    "hint_units": {
        "de": "Zuerst zusammenstecken (Ansicht von unten), dann gemeinsam aufsetzen.",
        "en": "Put these together first (view from below), then place them as one.",
    },
    "first": {"de": "zuerst", "en": "first"},
    "best_so_far_stable": {
        "de": (
            "Zeitgrenze erreicht: Das ist das beste stabile Modell, das bis dahin "
            "gefunden wurde. Mit mehr Rechenzeit käme es meist mit weniger Teilen aus."
        ),
        "en": (
            "Time limit reached: this is the best stable model found by then. With "
            "more computing time it would usually need fewer parts."
        ),
    },
    "best_so_far": {
        "de": (
            "Zeitgrenze erreicht, bevor ein stabiles Modell gefunden war: Das ist "
            "der letzte Zwischenstand."
        ),
        "en": (
            "Time limit reached before a stable model was found: this is the last "
            "intermediate result."
        ),
    },
    "layer_order": {
        "de": (
            "Die Schritte folgen den Schichten von unten nach oben. Das Modell "
            "ist groß, deshalb ist nicht jeder Zwischenstand auf Standfestigkeit "
            "geprüft: Stütze Überhänge beim Bauen mit der Hand."
        ),
        "en": (
            "The steps follow the layers from bottom to top. The model is large, "
            "so not every intermediate state was checked for stability: support "
            "overhangs with your hand while building."
        ),
    },
    "made_with": {
        "de": "Erstellt mit mesh2brick {version} am {date}.",
        "en": "Made with mesh2brick {version} on {date}.",
    },
    "trademark": {
        "de": (
            "LEGO® ist eine Marke der LEGO Gruppe, die dieses Projekt weder "
            "sponsert noch autorisiert oder unterstützt."
        ),
        "en": (
            "LEGO® is a trademark of the LEGO Group, which does not sponsor, "
            "authorise or endorse this project."
        ),
    },
    "page": {"de": "Seite {page} von {pages}", "en": "Page {page} of {pages}"},
    "finished": {"de": "Fertig!", "en": "Done!"},
}

_FAMILY: Final[dict[str, dict[Language, str]]] = {
    "brick": {"de": "Stein", "en": "Brick"},
    "plate": {"de": "Platte", "en": "Plate"},
    "tile": {"de": "Fliese", "en": "Tile"},
    "slope": {"de": "Dachstein", "en": "Slope"},
}


_COLOUR_DE: Final[dict[int, str]] = {
    # Descriptive German names for the catalogue colours (LDraw codes). Brand
    # names (Maersk, Fabuland) and oddities stay English only.
    0: "Schwarz",
    1: "Blau",
    2: "Grün",
    3: "Dunkeltürkis",
    4: "Rot",
    5: "Dunkelrosa",
    6: "Braun",
    7: "Hellgrau",
    8: "Dunkelgrau",
    9: "Blassblau",
    10: "Hellgrün",
    11: "Helltürkis",
    12: "Lachsrot",
    13: "Rosa",
    14: "Gelb",
    15: "Weiß",
    17: "Blassgrün",
    18: "Blassgelb",
    19: "Beige",
    20: "Hellviolett",
    22: "Lila",
    25: "Orange",
    26: "Magenta",
    27: "Limettengrün",
    28: "Dunkelbeige",
    29: "Hellrosa",
    30: "Mittellavendel",
    31: "Lavendel",
    68: "Pastellorange",
    70: "Rotbraun",
    71: "Hellblaugrau",
    72: "Dunkelblaugrau",
    73: "Mittelblau",
    74: "Mittelgrün",
    78: "Hellnougat",
    84: "Mittelnougat",
    85: "Mittelflieder",
    86: "Hellbraun",
    89: "Blauviolett",
    92: "Nougat",
    100: "Hell-Lachsrot",
    110: "Violett",
    112: "Mittelviolett",
    115: "Mittellimette",
    118: "Aquablau",
    120: "Hell-Limettengrün",
    121: "Hellorange",
    128: "Dunkelnougat",
    151: "Sehr helles Blaugrau",
    191: "Gelborange",
    212: "Hellblau",
    216: "Rostrot",
    220: "Hellflieder",
    225: "Warmes Gelborange",
    226: "Hellgelb",
    232: "Himmelblau",
    272: "Dunkelblau",
    288: "Dunkelgrün",
    308: "Dunkelbraun",
    320: "Dunkelrot",
    321: "Dunkelazur",
    322: "Mittelazur",
    323: "Hellaqua",
    326: "Gelbgrün",
    330: "Olivgrün",
    335: "Sandrot",
    351: "Mitteldunkelrosa",
    353: "Koralle",
    366: "Erdorange",
    370: "Mittelbraun",
    373: "Sandlila",
    378: "Sandgrün",
    379: "Sandblau",
    402: "Rotorange",
    424: "Ockergelb",
    430: "Warmrosa",
    462: "Mittelorange",
    484: "Dunkelorange",
    503: "Sehr helles Grau",
}


def colour_label(code: int, name: str, language: Language) -> str:
    """Colour name for the booklet.

    The catalogue name (``name``, as BrickLink and Rebrickable list it) in
    both languages; German adds a German name in brackets when one is known
    and differs (``Bright Green (Hellgrün)``, but ``Orange``).
    """
    name = name.replace("_", " ")
    german = _COLOUR_DE.get(code)
    if language == "de" and german and german.casefold() != name.casefold():
        return f"{name} ({german})"
    return name


def german_colour_names() -> dict[int, str]:
    """The German colour names by LDraw code (a copy, for checks and tests)."""
    return dict(_COLOUR_DE)


def text(key: str, language: Language, **values: object) -> str:
    """The text ``key`` in ``language``, with ``{placeholders}`` filled in.

    Raises:
        KeyError: for an unknown key.
    """
    return _TEXT[key][language].format(**values)


def number(value: float, language: Language, digits: int = 1) -> str:
    """``value`` with a decimal comma in German (``25,6``)."""
    formatted = f"{value:,.{digits}f}"
    if language == "de":
        return formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return formatted


def mass(grams: float, language: Language) -> str:
    """A readable mass: grams below 1 kg, else kilograms with one decimal."""
    if grams < 1000:  # noqa: PLR2004 - one kilogram
        return f"{round(grams):d} g"
    return f"{number(grams / 1000, language)} kg"


def subassembly_label(index: int) -> str:
    """Letters for sub-assemblies: A, B, ..., Z, AA, AB, ..."""
    label = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        label = chr(ord("A") + rest) + label
    return label


def part_size(part: PlacedPart) -> tuple[int, int, int]:
    """Footprint ``(short, long)`` in studs and height in plates of a part."""
    xs = {x for x, _, _ in part.cells}
    ys = {y for _, y, _ in part.cells}
    zs = {z for _, _, z in part.cells}
    short, long = sorted((len(xs), len(ys)))
    return short, long, len(zs)


def part_label(
    part: PlacedPart, language: Language, catalogue_name: str | None = None
) -> str:
    """Name of a part for the parts list.

    English uses Rebrickable's name when known; German (and English without
    a known name) describes family and size, like ``Platte 2 × 4``.
    """
    return sized_label(
        part.part, part.category, part_size(part), language, catalogue_name
    )


def sized_label(
    part: str,
    category: str,
    size: tuple[int, int, int],
    language: Language,
    catalogue_name: str | None = None,
) -> str:
    """Name of a part from its family and ``(short, long, height)`` size.

    English uses Rebrickable's name when known; otherwise the family and the
    size describe it, like ``Platte 2 × 4`` (heights in bricks when unusual).
    """
    if language == "en" and catalogue_name:
        return catalogue_name
    short, long, height = size
    family = _FAMILY.get(category)
    word = family[language] if family else part
    standard = {"brick": 3, "plate": 1, "tile": 1}.get(category)
    label = f"{short} × {long}"
    if standard is not None and height != standard:
        label += (
            f" × {number(height / 3, language, digits=0 if height % 3 == 0 else 1)}"
        )
    return f"{word} {label}"
