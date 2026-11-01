# mesh2brick

**Deutsch** · [English](README.md)

`mesh2brick` übersetzt ein 3D-Modell (STL, OBJ, 3MF, PLY, STEP, später `.blend`) in ein
**physisch baubares LEGO®-kompatibles Modell** und erzeugt daraus

1. eine **LDraw-Datei** (`.ldr`/`.mpd`) mit `0 STEP`-Bauschritten,
2. eine **Teileliste** als CSV, BrickLink-XML und Rebrickable-CSV,
3. eine **PDF-Bauanleitung** mit den benötigten Teilen pro Schritt.

Das Projekt baut auf dem GPL-Ökosystem rund um
[legolization](https://github.com/hbmartin/legolization) (Steine platzieren,
Stabilität, Bauschritte), [pyldraw3](https://github.com/hbmartin/pyldraw3)
(LDraw-Bibliothek) und [rebrickable](https://github.com/hbmartin/rebrickable)
(Offline-Katalog) auf. mesh2brick ergänzt den Mesh-/CAD-Import, die Farbübernahme,
einen größeren Teilekatalog, schönere Anleitungen, eine einheitliche Konfiguration
und CLI sowie eine optionale KI-Schicht.

> **Stand: Vorab-Version (Phase 0 von 8).** Das Projektgerüst und die Anbindung an
> legolization funktionieren, der Mesh-Import kommt in Phase 1. Details stehen in
> [docs/STATUS.md](docs/STATUS.md).

## Installation (Entwicklung)

Voraussetzungen: Python ≥ 3.12 und [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run ldraw download --yes   # einmalig: LDraw-Teilebibliothek (~150 MB)
uv run ldraw generate --yes   # einmalig: Teile-/Farbmodule erzeugen
uv run mesh2brick --help
```

## Benutzung

```sh
# Phase 0: Steine auf ein Voxelmodell setzen, LDraw + Vorschaubild schreiben
uv run mesh2brick place tests/fixtures/heart.vox -o out/

# Jede Einstellung aus mesh2brick.yaml lässt sich auf der Kommandozeile überschreiben
uv run mesh2brick place modell.vox --set placement.strategy=greedy --set placement.seed=3

# Vorschau eines fertigen Modells, optional bis zu einem Bauschritt
uv run mesh2brick render out/heart.bricks.json --step 3
```

Geplant ist `mesh2brick convert modell.stl` (Phase 2), das die ganze Pipeline in einem
Schritt ausführt. Alle Einstellungen sind in
[examples/mesh2brick.yaml](examples/mesh2brick.yaml) beschrieben.

## Entwicklung

```sh
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
uv run pre-commit install
```

Commits folgen [Conventional Commits](https://www.conventionalcommits.org/) und tragen
ein DCO-Sign-off (`git commit -s`). Architekturentscheidungen stehen in
[docs/adr/](docs/adr/), die Lizenzen der Abhängigkeiten in
[docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

## Lizenz

GPL-3.0-or-later, siehe [LICENSE](LICENSE). LEGO® ist eine Marke der LEGO Gruppe, die
dieses Projekt weder unterstützt noch autorisiert.
