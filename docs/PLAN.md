# Umsetzungsplan Phase 0–2

Stand: 2026-11-01 · Grundlage: `SPEC.md` · Fortschritt: `docs/STATUS.md`

## Was ich vorgefunden habe

Bevor ich geplant habe, habe ich legolization 0.5.0, pyldraw3 1.7.0 und rebrickable 1.1.0
installiert und ihren Quellcode gelesen. Die wichtigsten Erkenntnisse:

- **legolization kann mehr, als die SPEC voraussetzt.** Es hat bereits einen eigenen Mesh-Import
  (OBJ/STL/PLY), Hohl-Machen, sieben Platzierungsstrategien, Slopes/Tiles, Stabilitätsprüfung,
  Bauschritte, Teileliste (JSON/Text) und ein PDF/HTML-Heft (reportlab). Die Bilder pro Schritt
  im PDF entstehen nur, wenn LeoCAD oder LDView installiert ist, sonst gibt es Platzhalter-Kästen.
- **Datenformat:** legolization erwartet ein Gitter `(x, y, layer)` mit Schichten in
  **Plattenhöhe** (1 Brick = 3 Schichten), Z nach oben, Werte = LDraw-Farbcode, `-1` = leer.
  Das passt direkt zu unserem Z-up-Gitter. Die Umrechnung ins LDraw-System (−Y oben) macht
  legolization beim Schreiben der `.ldr`. Unsere „eine Stelle" für den Übergang ist deshalb
  `backends/legolization.py`, abgesichert durch einen Round-Trip-Test (Gitter → `.ldr` → Positionen
  zurücklesen → identisch).
- **Die LDraw-Teilebibliothek ist Pflicht** (147 MB Download, entpackt 623 MB unter
  `~/Library/Caches/pyldraw3`, also außerhalb von Repo und Nextcloud). Ohne sie startet
  legolization nicht. In CI wird sie einmal geladen und gecacht.
- **Smoke-Test funktioniert:** `heart.vox` → 12 Steine, 8 Schritte, stabil, in ~1 Sekunde.
- legolization liefert keine Typ-Markierung (`py.typed`), deshalb braucht mypy eine Sonderregel.
  Das ist der erste Upstream-Kandidat.
- `samples/Duo_Duolingo.*` ist ein gutes echtes Testmodell, gehört aber **nicht** ins öffentliche
  Repo (Markenrecht, 105 MB). Es wird per `.gitignore` ausgeschlossen und nur lokal getestet.

## Entscheidungen, die ich getroffen habe

| # | Entscheidung | Warum | ADR |
|---|---|---|---|
| 1 | Die Python-Umgebung `.venv` ist ein Symlink nach `~/.local/share/venvs/mesh2brick`. | Nextcloud würde sonst über 150 MB und tausende Dateien synchronisieren. Symlinks synchronisiert Nextcloud nicht. | – (STATUS) |
| 2 | `dev`-Werkzeuge kommen in eine uv-*dependency-group* statt in ein Extra. | uv installiert sie bei `uv sync` automatisch, und das ist der heutige Standard. Die Extras `step`, `blender` und `llm` bleiben wie in der SPEC. | – |
| 3 | Wir behalten eine **eigene Voxelisierung**, legolizations Mesh-Import dient als Vergleich. | Die SPEC verlangt Belegung nach Volumenanteil mit Schwellwert, einen Brick/Plate-Modus, 3MF/STEP und Farbmodi. legolization füllt nur binär die Oberfläche auf. Im Benchmark vergleichen wir beide. | 0003 (Phase 1) |
| 4 | Bei `fill: hollow` bleibt unser Gitter voll, und das Aushöhlen übernimmt legolization (Wandstärke wird übersetzt). | legolization füllt bei Instabilität gezielt Säulen wieder auf. Das geht nur, wenn es das volle Modell kennt. Unser eigenes Aushöhlen per Erosion gibt es trotzdem für Vorschau, Statistik und `.vox`-Export. | 0004 (Phase 1) |
| 5 | Eigener Datentyp `BrickModel` (JSON-serialisierbar) zwischen Backend und Rest des Programms. | Nur `backends/` darf legolization importieren. Renderer, BOM und LLM-Schicht arbeiten deshalb auf unserem eigenen Typ. | 0003-ff. |
| 6 | Eigener Vorschau-Renderer mit matplotlib (Steine als Quader). | Er liefert die Galerie-Bilder, die Selbstkontrolle und Ersatz-Schrittbilder fürs PDF, wenn weder LeoCAD noch LDView vorhanden sind (z. B. in CI). | – |
| 7 | BOM: CSV selbst. Rebrickable-CSV und BrickLink-XML entstehen über das `rebrickable`-Paket. | Teilenummern und Farbcodes werden nicht geraten. Falls der Rebrickable-Offline-Katalog in Phase 2 noch zu schwer ist, nehmen wir eine kleine, mit Quelle dokumentierte Tabelle der Volltonfarben, die Phase 4 durch den Katalog ersetzt. | Phase 2 |

## Phase 0 – Gerüst (diese Session)

- [x] `uv init`, `pyproject.toml` mit Extras `step`, `blender`, `llm` und dev-Gruppe; legolization, pyldraw3 und rebrickable exakt gepinnt.
- [x] `ruff` (lint + format), `mypy --strict` für `src/`, `pytest` + `pytest-cov`, `pre-commit`.
- [x] Paketgerüst nach SPEC §3 (Module als leere, dokumentierte Platzhalter, wo noch nichts passiert).
- [x] `config.py`: komplettes pydantic-Schema aus SPEC §4, YAML-Loader, CLI-Overrides (`--set voxel.fill=solid`), klare Fehlermeldungen.
- [x] `backends/protocols.py` (Placer, StabilityChecker, StepSequencer, Exporter), `backends/legolization.py` (Gitter → Platzierung → `.ldr`), `backends/pyldraw.py` (Bibliotheks-Check, Farbtabelle).
- [x] `BrickModel` + minimaler PNG-Renderer (für `docs/gallery/`).
- [x] CLI (`typer`): `convert | voxelize | place | render | catalog | inspect | feedback`. In Phase 0 funktioniert `place` für `.vox`/`.npy`, die übrigen Befehle melden „kommt in Phase N".
- [x] Tests: CLI-Hilfe, Config-Validierung, **Smoke-Test heart.vox → .ldr**, Architekturregel (nur `backends/` importiert legolization & Co.) und SPDX-Header als automatischer Test.
- [x] GitHub-Actions-Workflow (Linux + macOS, Python 3.12/3.13, LDraw-Bibliothek gecacht).
- [x] `CLAUDE.md`, `README.md`, `README.de.md`, `LICENSE`, ADR 0001/0002, `THIRD_PARTY.md`, `UPSTREAM.md`, `STATUS.md`, `CHANGELOG.md`, Galeriebild.
- [x] Git-Repo, erster Commit (DCO), Tag `v0.0.0`.
- [x] GitHub-Repo anlegen und pushen (nach deinem OK, öffentlich, noreply-Adresse), CI grün.
- **Abnahme:** `uv run mesh2brick --help` läuft, Smoke-Test grün in CI.

## Phase 1 – Ingest + Voxelisierung

- [x] `ingest/`: Loader-Registry nach Dateiendung, STL/OBJ/PLY via trimesh, 3MF mit eigenem Leser (inkl. Production Extension der Slicer). Normalisierung: Hochachse → Z, Einheit mm (3MF-Einheiten auswerten), Wasserdichtheit prüfen und reparieren, sonst Warnung und Fallback auf Oberflächen-Voxelisierung.
- [x] `voxel/voxelize.py`: **Spalten-Rasterung**. Pro Noppe 4×4 Abtaststrahlen in Z-Richtung. Pro Strahl werden die Ein- und Austrittspunkte am Mesh bestimmt (Windungszahl, robust gegen überlappende Teile), daraus folgt exakt, wie viel jeder Voxel in der Höhe gefüllt ist. Belegt ist ein Voxel ab `threshold` (Standard 0,5). Das ist schnell genug für Meshes mit Millionen Dreiecken (Duo-STL: ~2 Mio.).
- [x] Nicht-kubische Voxel: 1 × 1 Noppe × 1,2 Noppen (`brick`) oder × 0,4 (`plate`). Skalierung über `target_studs` oder `mm_per_stud`.
- [x] Rundungsregel (wird dokumentiert): Das Gitter beginnt am Boden des Modells (Z = 0). In X/Y wird das Modell im Gitter zentriert, die Zahl der Voxel ist `round(Ausdehnung / Raster)`, mindestens 1. Würfel 10 mm bei 8 mm/Noppe → 1,25 → 1 Noppe; Höhe 10 mm / 9,6 mm → 1 Brick.
- [x] `voxel/grid.py` (`VoxelGrid`, unveränderlich), `voxel/color.py` (Modi `single`, `height_bands`), Aushöhlen per Erosion.
- [x] `voxel/io.py`: `.npz` intern; `.npy` (int-Codes, `-1` leer) und `.vox` (MagicaVoxel, mit RGBA-Palette) genau so, wie legolization sie liest. Round-Trip-Tests über legolizations eigenen Loader.
- [x] Fixtures per Skript erzeugt (`scripts/make_fixtures.py`, CC0): Würfel, Kugel, L-Winkel, Torus und ein selbst gebauter Low-Poly-Hase. Einen CC-lizenzierten Scan-Hasen gibt es nicht.
- [x] CLI `voxelize` mit PNG-Vorschau, `docs/benchmarks.md` (eigene Voxelisierung gegen legolization.mesh).
- **Abnahme:** Würfel → 1×1×1; Kugel bei `target_studs: 32` < 15 % Volumenabweichung; alle Fixtures laufen ohne Fehler durch legolization.

## Phase 2 – End-to-End (MVP)

- [ ] `mesh2brick convert bunny_lowpoly.stl` → `.ldr` + BOM (CSV, BrickLink-XML, Rebrickable-CSV) + PDF.
- [ ] PDF zunächst über legolizations Booklet. Für die Schrittbilder wird LeoCAD per Homebrew installiert (von dir freigegeben). Ohne Renderer, z. B. in CI, nehmen wir unsere matplotlib-Bilder.
- [ ] Prüfung: BOM-Summe = Teilezahl = Anzahl `1`-Zeilen in der `.ldr`, jeder Stein steckt in genau einem Schritt.
- [ ] Abgleich legolization-PDF ↔ SPEC §1 und Lückenliste in `STATUS.md` (wird in Phase 6 geschlossen).
- [ ] Upstream-Kandidaten in `UPSTREAM.md` sammeln.
- [ ] Lokaler Testlauf mit Duo als erster echter Praxistest (nur lokal: nicht ins Repo, nicht in die Galerie).
- **Abnahme:** PDF für den Hasen öffnet, Schritte vollständig, BOM-Summe = Teilezahl, `.ldr` öffnet in LDView/Studio (Screenshot in `docs/gallery/`).

## Risiken und wie ich damit umgehe

- **Laufzeit großer Modelle:** legolization optimiert Stabilität mit LP-Solvern. Standard sind jetzt 32 Noppen, 48 kommt später. Bei 48 können Modelle mit tausenden Steinen entstehen. Gegenmaßnahme: Zeitbudget (`time_budget_s`) durchreichen und Laufzeiten in `docs/benchmarks.md` festhalten.
- **CI-Dauer:** Die Bibliothek ist 147 MB groß. Die Generierung wird gecacht, Schlüssel ist die Bibliotheksversion.
- **Nextcloud + Git:** Das `.git`-Verzeichnis wird mitsynchronisiert. Das ist unkritisch, solange nur ein Rechner gleichzeitig daran arbeitet.
