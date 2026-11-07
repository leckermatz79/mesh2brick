# mesh2brick

**Deutsch** · [English](README.md)

`mesh2brick` übersetzt ein 3D-Modell (STL, OBJ, 3MF, PLY, STEP, später `.blend`) in ein
**physisch baubares LEGO®-kompatibles Modell** und erzeugt daraus

1. eine **LDraw-Datei** (`.ldr`/`.mpd`) mit `0 STEP`-Bauschritten,
2. eine **Teileliste** als CSV, BrickLink-XML und Rebrickable-CSV,
3. eine **PDF-Bauanleitung** auf Deutsch oder Englisch: Deckblatt mit Bild und Maßen,
   Teileliste mit Bildern, Schritte mit Teilebildern und verständlichen Hinweisen.

Das Projekt baut auf dem GPL-Ökosystem rund um
[legolization](https://github.com/hbmartin/legolization) (Steine platzieren,
Stabilität, Bauschritte), [pyldraw3](https://github.com/hbmartin/pyldraw3)
(LDraw-Bibliothek) und [rebrickable](https://github.com/hbmartin/rebrickable)
(Offline-Katalog) auf. mesh2brick ergänzt den Mesh-/CAD-Import, die Farbübernahme,
einen größeren Teilekatalog, schönere Anleitungen, eine einheitliche Konfiguration
und CLI sowie eine optionale KI-Schicht.

> **Stand: Vorab-Version (Phase 6 von 8).** `mesh2brick convert` macht aus STL, OBJ, PLY,
> 3MF und STEP ein LDraw-Modell, drei Teilelisten und eine PDF-Bauanleitung, in den Farben
> des Modells. Details stehen in [docs/STATUS.md](docs/STATUS.md).

## Installation (Entwicklung)

Voraussetzungen: Python ≥ 3.12 und [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run ldraw download --yes   # einmalig: LDraw-Teilebibliothek (~150 MB)
uv run ldraw generate --yes   # einmalig: Teile-/Farbmodule erzeugen
uv run mesh2brick --help
uv sync --extra step          # optional: STEP-Import (OpenCASCADE über cascadio, ~70 MB)
```

## Benutzung

```sh
# Alles in einem Schritt: LDraw, Teilelisten (CSV, BrickLink-XML, Rebrickable-CSV), PDF
uv run mesh2brick convert tests/fixtures/bunny_lowpoly.stl -o out/ --set input.target_studs=16

# Oder Schritt für Schritt:
# 1. Mesh auf das Noppenraster voxelisieren (längste Achse standardmäßig 32 Noppen)
uv run mesh2brick voxelize tests/fixtures/bunny_lowpoly.stl -o out/ --set input.target_studs=16

# 2. Steine auf das Gitter setzen: LDraw-Datei, Steinmodell (JSON), PNG-Vorschau
uv run mesh2brick place out/bunny_lowpoly.grid.npz -o out/

# Voxeldateien gehen auch (MagicaVoxel .vox, numpy .npy)
uv run mesh2brick place tests/fixtures/heart.vox -o out/

# Farben kommen aus dem Modell, wenn es welche hat (Filamente und Materialien in 3MF,
# STEP-Farben, OBJ/glTF-Materialien und -Texturen, PLY-Vertexfarben). Sie werden auf
# ~40 aktuelle LEGO-Farben abgebildet. Stattdessen alles in einer Farbe:
uv run mesh2brick convert tests/fixtures/toadstool.obj -o out/ --set color.mode=single

# Teile ansehen (offline): Größen, BrickLink-/Rebrickable-Nummern, Farben
uv run mesh2brick catalog list --category slope
uv run mesh2brick catalog show 3001

# Nur bestimmte Teile verwenden (Whitelist) oder Teile verbieten (Blacklist)
uv run mesh2brick convert modell.stl -o out/ --set "parts.include=[3001, 3003, 3004]"
uv run mesh2brick convert modell.stl -o out/ --set "parts.exclude=[3008, 3007]"

# Jede Einstellung aus mesh2brick.yaml lässt sich auf der Kommandozeile überschreiben
uv run mesh2brick place modell.vox --set placement.strategy=greedy --set placement.seed=3

# Anleitung auf Englisch, 4 Schritte pro Seite, flache .ldr statt .mpd
uv run mesh2brick convert modell.stl -o out/ --set output.language=en \
    --set output.steps_per_page=4 --set "output.formats=[ldr, bom_csv, pdf]"

# Vorschau eines fertigen Modells, optional bis zu einem Bauschritt
uv run mesh2brick render out/heart.bricks.json --step 3
```

Alle Einstellungen sind in [examples/mesh2brick.yaml](examples/mesh2brick.yaml)
beschrieben.

## Die Bauanleitung

- **Deckblatt:** Bild des Modells, Zahl der Teile und Schritte, Größe in cm, Gewicht,
  Farben und ob das Modell von allein steht.
- **Teileliste:** eine Kachel pro Teil und Farbe mit Bild (alle im selben Maßstab),
  Anzahl, Name und LDraw-Nummer; ein Hinweis, wenn LEGO ein Teil in der Farbe nicht
  herstellt.
- **Schritte (1–4 pro Seite):** neue Teile in voller Farbe, frühere blass, darüber alle
  neuen Teile als Bilder. Baugruppen werden auf blauem Feld gebaut und dann aufgesetzt.
  Ein kleines gelbes Feld „zuerst“ zeigt Teile, die man vorher in der Hand
  zusammensteckt (ein Teil unter einem Überhang zusammen mit dem Teil, das es hält).
- **Große Modelle (über 500 Teile)** bekommen Schritte Schicht für Schicht, ohne dass
  jeder Zwischenstand auf Standfestigkeit geprüft ist; das steht auf dem Deckblatt.
- Farbnamen bleiben wie bei BrickLink und Rebrickable (englisch), damit man sie dort
  findet.

## Ergebnisse in anderen Programmen öffnen

- **BrickLink Studio:** die `.mpd` (oder `.ldr`) über **Datei → Öffnen** laden. Unter macOS hing
  Studios **Import** in unserem Test bei jeder Datei (auch bei Studios eigenem Export);
  Datei → Öffnen lädt dieselbe Datei sofort. Eine Duo-Testdatei zeigte in Studio keine
  Überlappungen, keine Duplikate und keine Stabilitätsprobleme.
- LDraw-Betrachter (LDView, LeoCAD) öffnen die Dateien direkt. In der `.mpd` ist jede
  Baugruppe ein eigenes Untermodell mit eigenen Schritten.

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
