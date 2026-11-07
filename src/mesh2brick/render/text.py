# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Words for the building instructions, in German and English.

All user-facing text of the PDF lives here, written for builders, not for
engineers: no stability scores, no solver names. Part names come from
Rebrickable in English; German names are built from the part's family and
size (``Stein 2 × 4``). Colour names stay the catalogue names in both
languages (``Bright Green``), so they can be found in BrickLink and
Rebrickable shops as written.
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
    if language == "en" and catalogue_name:
        return catalogue_name
    short, long, height = part_size(part)
    family = _FAMILY.get(part.category)
    word = family[language] if family else part.part
    standard = {"brick": 3, "plate": 1, "tile": 1}.get(part.category)
    size = f"{short} × {long}"
    if standard is not None and height != standard:
        size += f" × {number(height / 3, language, digits=0 if height % 3 == 0 else 1)}"
    return f"{word} {size}"
