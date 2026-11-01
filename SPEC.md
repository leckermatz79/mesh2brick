# Projektauftrag für Claude Code: `mesh2brick`

> Verwendung: Diese Datei als `SPEC.md` ins leere Repo legen, Claude Code im Repo-Ordner starten und mit
> „Lies SPEC.md vollständig, erstelle einen Umsetzungsplan für Phase 0–2 und beginne danach mit Phase 0."
> loslegen. Jede weitere Session: „Lies SPEC.md und CLAUDE.md, prüfe docs/STATUS.md und mache mit der nächsten offenen Phase weiter."
>
> Dieses Projekt wird im „Vibe-Coding"-Modus entwickelt: Der Nutzer ist Product Owner, nicht Fachexperte für LEGO-Design oder Geometrie-Algorithmen. Claude Code trifft Fachentscheidungen eigenständig, dokumentiert sie verständlich und holt sich nur bei Geschmacks- und Zielfragen Rückmeldung (siehe §8).

---

## 1. Ziel

`mesh2brick` ist ein Open-Source-Python-Werkzeug (CLI + Bibliothek), das ein digitales 3D-Modell
(STL, OBJ, 3MF, PLY, STEP, später .blend) in ein **physisch baubares LEGO®-kompatibles Modell** übersetzt und daraus

1. eine **LDraw-Datei** (`.ldr`/`.mpd`) mit `0 STEP`-Bauschritten,
2. eine **Teileliste** (BOM) als CSV, BrickLink-XML und Rebrickable-CSV,
3. eine **PDF-Bauanleitung** (Schritt-für-Schritt, mit Teile-Callouts pro Schritt)

erzeugt. Eine optionale **LLM-Schicht** (Anthropic API) übernimmt Ermessensentscheidungen (Teilewahl bei Mehrdeutigkeit, Unterbaugruppen, Schrittgliederung, Erklärtexte) und lernt aus Nutzerfeedback. Die Geometrie-Pipeline muss **ohne** LLM vollständig funktionieren.

### Strategie: Aufbauen statt Nachbauen
`mesh2brick` baut auf dem bestehenden GPL-Ökosystem auf und ist **kein Fork**, sondern ein Wrapper mit eigenen Erweiterungen:

- **`legolization`** (hbmartin, GPL-3.0-or-later): Voxel → Steine, Stabilität (RBE/LP), Reparatur, Bauschritte, LDraw-Export, PDF-Grundgerüst.
- **`pyldraw3`** (GPL-3.0-or-later): LDraw-Bibliothek, Teile- und Farbmodule, Schreiben von `.ldr`/`.mpd`.
- **`rebrickable`** (GPL-3.0-or-later): Offline-Katalog, Teile-Metadaten, LDraw-Brücke.
- **BrickGPT/LegoGPT** (MIT): Referenz für die Stabilitäts-Formulierung und Trainingsdaten (StableText2Brick), nicht als Laufzeit-Abhängigkeit.

Eigener Mehrwert von `mesh2brick` liegt dort, wo diese Werkzeuge nichts bieten: **Mesh-/CAD-Ingest** (STL, 3MF, STEP, Blender), **Farbübernahme** aus Mesh/Textur/CAD, **Katalog-Erweiterung** über Brick/Plate/Slope hinaus, **LLM-Schicht**, **Anleitungsqualität** (Layout, Callouts, Sprache) und eine **einheitliche Konfiguration/CLI**.

**Upstream-first:** Verbesserungen, die allgemein nützlich sind (Bugfixes, neue Strategien, Exportformate), werden als PR an `legolization`/`pyldraw3` eingereicht, nicht lokal gepatcht. Lokale Patches nur als Übergang, mit Issue-Link in `docs/UPSTREAM.md`. Geforkt wird erst, wenn Upstream-PRs nicht angenommen werden oder die Richtungen auseinanderlaufen – diese Entscheidung trifft der Nutzer.

### Nicht-Ziele (v1)
- Keine Technic-/Pin-/Achsenkonstruktionen, keine Minifiguren, keine Flexteile.
- Kein SNOT (Studs Not On Top) in v1; Studrichtung = +Z des Eingabemodells (konfigurierbar).
- Keine Web-UI. CLI und Python-API reichen.
- Keine GUI-Abhängigkeit (Blender nur headless, Studio nur optional als externer Renderer).

---

## 2. Technischer Rahmen

| Bereich | Vorgabe |
|---|---|
| Sprache | Python ≥ 3.12, vollständig typisiert (`mypy --strict` für `src/`) |
| Paketverwaltung | `uv`, `pyproject.toml` (PEP 621), `src/`-Layout |
| Qualität | `ruff` (lint + format), `mypy`, `pytest` + `pytest-cov`, `pre-commit` |
| CLI | `typer`; Konfiguration via `pydantic` v2 + YAML-Datei + CLI-Overrides |
| Geometrie | `numpy`, `scipy`, `trimesh` (STL/OBJ/3MF/PLY); STEP über optionales Extra `step` (2026-11-01: `cascadio` statt `cadquery`/`OCP`, gleiche OpenCASCADE-Basis, deutlich kleiner, ADR 0007) |
| LEGO-Pipeline | `legolization`, `pyldraw3`, `rebrickable` als reguläre Abhängigkeiten, Versionen gepinnt; Upgrade pro Minor-Release bewusst mit Changelog-Lektüre |
| Optimierung | nur was legolization nicht abdeckt; `scipy.optimize.linprog` (HiGHS) bevorzugt, keine proprietären Solver (kein Gurobi) |
| LLM | `anthropic` SDK, Modell per Config, Default `claude-sonnet-5-5` (nicht hartkodieren) |
| PDF | legolization-PDF als Basis evaluieren; falls unzureichend `reportlab` oder `weasyprint` (ADR) |
| CI | GitHub Actions: lint, type-check, tests auf Linux + macOS, Python 3.12/3.13 |
| **Lizenz** | **GPL-3.0-or-later** für das gesamte Projekt (ADR 0002). SPDX-Header in jeder Quelldatei. Übernommener oder adaptierter Fremdcode behält Original-Copyright und wird mit Quelle, Lizenz und Commit-Hash im Dateikopf markiert. Alle Abhängigkeiten mit Lizenz in `docs/THIRD_PARTY.md`; nur GPL-kompatible Lizenzen (MIT, BSD, Apache-2.0, LGPL, GPL). |
| Beiträge | DCO-Sign-off (`git commit -s`), kein CLA |
| Sprache im Code | Code, Kommentare, Docstrings, Commits, Issues: Englisch. Nutzerdokumentation: Deutsch + Englisch (`README.md`, `README.de.md`) |

### LDraw-Grundlagen (verbindlich)
- Einheit LDU: 1 Noppe = 20 LDU in X/Z, Brick-Höhe = 24 LDU, Plate-Höhe = 8 LDU (1 Brick = 3 Plates).
- LDraw-Koordinatensystem: **−Y zeigt nach oben**. Eingabemodelle werden intern in ein Z-up-Voxelgitter gebracht und erst beim Übergang zu legolization/pyldraw3 transformiert – genau eine Stelle im Code, mit Round-Trip-Test.
- Teile-IDs und Farbcodes nur aus der lokalen LDraw-Bibliothek (`pyldraw3`), nie raten.
- Farben: RGB → nächste **solide** LDraw-Farbe (Metallic/Transparent nur bei explizitem Opt-in).

---

## 3. Architektur

```
src/mesh2brick/
├─ __init__.py
├─ cli.py               # typer-App: convert | voxelize | place | render | catalog | inspect | feedback
├─ config.py            # pydantic Settings + YAML-Loader
├─ ingest/              # Dateiformate → trimesh.Trimesh (normalisiert, Z-up, mm)
│   ├─ base.py          # Protocol Loader; Registry nach Dateiendung
│   ├─ mesh_formats.py  # STL/OBJ/3MF/PLY via trimesh
│   ├─ step.py          # STEP via cascadio (Extra "step", ADR 0007), Tessellierung, STEP-Farben
│   └─ blender.py       # .blend via `blender --background --python` (Extra "blender")
├─ voxel/
│   ├─ grid.py          # VoxelGrid: occupancy bool[X,Y,Z], color int32[X,Y,Z] (LDraw-Codes), pitch, origin
│   ├─ voxelize.py      # Mesh → Grid, Stud-Raster, Höhenmodus brick|plate, Hohlkörper, Wandstärke
│   ├─ color.py         # Vertex-/Textur-/CAD-Farben → LDraw-Farbcodes
│   └─ io.py            # .npz (intern), .npy + .vox (legolization-kompatibel)
├─ backends/            # Adapter zu Fremdbibliotheken – einzige Stelle mit Imports aus legolization & Co.
│   ├─ protocols.py     # Placer, StabilityChecker, StepSequencer, Exporter als typing.Protocol
│   ├─ legolization.py  # Implementiert alle Protocols über legolization.PipelineConfig/run
│   └─ pyldraw.py       # Bibliothekszugriff, Teile-Geometrie, Farbtabellen
├─ catalog/
│   ├─ parts.py         # PartSpec: id, footprint, height_plates, stud_mask, category – aus pyldraw3 abgeleitet
│   ├─ rebrickable.py   # Metadaten, Verfügbarkeit, Namen (offline-Katalog; 2026-11-01: aus mitgelieferter, generierter Tabelle statt rebrickable-Datenbank, ADR 0009)
│   └─ whitelist.py     # Teile-Whitelist aus Config → an Backend durchgereicht
├─ place/               # eigene Strategien, die das Placer-Protocol erfüllen (erst ab Phase 5)
├─ steps/               # eigene Schrittlogik, falls legolization nicht reicht (Phase 6)
├─ agent/               # optional, Extra "llm"
│   ├─ client.py        # Anthropic-Client, Tools: catalog_lookup, stability_check, render_preview
│   ├─ tasks.py         # choose_part, group_steps, write_step_text
│   └─ feedback.py      # SQLite-Store: Bewertungen → Few-Shot-Beispiele
├─ export/
│   └─ bom.py           # CSV, BrickLink-XML, Rebrickable-CSV (LDraw-Export kommt vom Backend)
└─ render/
    ├─ scene.py         # Kamera, Explosionsansicht, Callouts pro Schritt
    ├─ preview.py       # PNG-Vorschau (matplotlib) für Selbstkontrolle und STATUS-Berichte
    └─ pdf.py           # Seitenlayout: Deckblatt, BOM, Schrittseiten, de/en
```

Regeln:
- Kein Modul außerhalb `backends/` importiert `legolization`, `pyldraw3` oder `rebrickable` direkt. So bleibt ein späterer Backend-Wechsel oder Fork lokal begrenzt.
- Jede Pipeline-Stufe ist einzeln per CLI ausführbar und ihre Zwischenstände (`VoxelGrid`, `BrickModel`) serialisierbar.
- Reine Funktionen auf unveränderlichen Datentypen (`dataclass(frozen=True)` oder pydantic).

---

## 4. Konfiguration (`mesh2brick.yaml`)

```yaml
input:
  up_axis: z            # x|y|z, optional negativ "-y"
  auto_orient: false
  scale_mode: studs     # studs|mm
  target_studs: 32      # längste Achse in Noppen (PO-Entscheidung 2026-11-01: Standard 32, 48 erst später)
  mm_per_stud: 8.0
  multi_body: union     # union|error (Phase 3: Mehrkörper vereinigen oder ablehnen)
  step_tolerance_mm: 0.05   # Phase 3: Tessellierungs-Toleranz für STEP
voxel:
  height_unit: brick    # brick|plate
  fill: hollow          # solid|hollow
  wall_thickness: 2
  threshold: 0.5
color:
  mode: auto            # auto|single|vertex|texture|cad|height_bands (2026-11-01: auto = Farben aus dem Modell, falls vorhanden, sonst single_color; vorher single, ADR 0008)
  single_color: 4       # LDraw-Code
  palette: common       # common|solid|all (2026-11-01: common = ~40 aktuelle LEGO-Farben, Standard; solid = alle Volltonfarben mit Katalognummern; all = alle LDraw-Volltonfarben, ADR 0008)
parts:
  categories: [brick, plate]   # slope vorübergehend opt-in (2026-11-01): legolization 0.5.0 wird damit bis zu 50x langsamer, siehe docs/UPSTREAM.md #2
  include: []
  exclude: []
  max_parts: 5000
placement:
  backend: legolization
  strategy: kollsker    # wird 1:1 an legolization durchgereicht; Standard per Benchmark (2026-11-01, docs/benchmarks.md), vorher luo
  seed: 0
stability:
  enabled: true
  max_repair_iterations: 20
steps:
  parts_per_step: 7
  keep_symmetry: true
  submodels: true
llm:
  enabled: false
  model: claude-sonnet-5-5
  tasks: [group_steps, write_step_text]
output:
  dir: ./out
  formats: [ldr, bom_csv, bom_bricklink, bom_rebrickable, pdf]   # bom_rebrickable ergänzt (2026-11-01), damit convert die drei BOM-Formate aus Phase 2 liefert
  language: de
  page_size: A4
```

Jeder Parameter ist per CLI überschreibbar. Ungültige Kombinationen werden beim Laden mit klarer Fehlermeldung abgelehnt. Backend-spezifische Optionen (legolization-Strategien, Presets) werden nicht dupliziert, sondern per `placement.backend_options: {}` durchgereicht und validiert.

---

## 5. Phasen mit Abnahmekriterien

Jede Phase endet mit: Tests grün, `ruff`/`mypy` sauber, `docs/STATUS.md` aktualisiert, Eintrag in `CHANGELOG.md`, Git-Tag `v0.<phase>.0`, ein PNG-Vorschaubild des aktuellen Ergebnisses in `docs/gallery/`.

### Phase 0 – Gerüst
- `uv init`, `pyproject.toml` mit Extras `step`, `blender`, `llm`, `dev`; `legolization`, `pyldraw3`, `rebrickable` als Abhängigkeiten pinnen.
- `ruff`, `mypy`, `pytest`, `pre-commit`, GitHub-Actions-Workflow.
- `CLAUDE.md` (§7), `README.md` + `README.de.md`, `LICENSE` (GPL-3.0-or-later), `docs/adr/0001-record-architecture-decisions.md`, `docs/adr/0002-license-gpl-and-build-on-legolization.md`, `docs/THIRD_PARTY.md`, `docs/UPSTREAM.md` (leer), `docs/STATUS.md`.
- Smoke-Test: legolization-Beispiel (`heart.vox`) über `backends/legolization.py` ausführen und `.ldr` erzeugen.
- **Abnahme:** `uv run mesh2brick --help` läuft; Smoke-Test grün in CI.

### Phase 1 – Ingest + Voxelisierung
- Loader für STL/OBJ/3MF/PLY. Normalisierung: Z-up, mm, Wasserdichtheit prüfen (`trimesh.repair`), Fallback auf Oberflächen-Voxelisierung mit Warnung.
- Voxelisierung auf Stud-Raster mit nicht-kubischen Voxeln (Höhe 1,2 Noppen bei `brick`, 0,4 bei `plate`), Belegung per Volumenanteil.
- Hohlkörper per morphologischer Erosion; Farbmodi `single` und `height_bands`.
- `voxel/io.py`: `.npz` intern, `.npy`/`.vox` exakt im Format, das legolization einliest (Dokumentation und Quellcode von legolization prüfen; Round-Trip-Test).
- Fixtures in `tests/fixtures/`: `cube_10mm.stl`, `sphere_r10.stl`, `l_bracket.stl` (Überhang), `torus.stl` (Hohlraum), `bunny_lowpoly.stl` (CC-lizenziert, Quelle dokumentieren).
- **Abnahme:** Würfel 10 mm bei `mm_per_stud: 8` → 1×1 Noppe, 1 Brick hoch (Rundungsregel dokumentiert). Kugel: Volumenabweichung < 15 % bei `target_studs: 32`. Alle Fixtures laufen ohne Fehler durch legolization.

### Phase 2 – End-to-End (MVP)
- `mesh2brick convert bunny_lowpoly.stl` → `.ldr` + BOM (3 Formate) + PDF, komplett über das legolization-Backend.
- Vergleich der legolization-PDF mit den Anforderungen aus §1; Lücken als Liste in `docs/STATUS.md` (werden in Phase 6 geschlossen).
- Erste Upstream-Kandidaten identifizieren (z. B. Format-Erweiterungen, Bugs) und in `docs/UPSTREAM.md` sammeln.
- **Abnahme:** PDF für den Hasen öffnet, Schritte vollständig, BOM-Summe = Teilezahl, `.ldr` öffnet in LDView/Studio (manuell, Screenshot in `docs/gallery/`).

### Phase 3 – STEP + Farben
- `cadquery`/`OCP`-Loader, Tessellierung mit Toleranz, Mehrkörper → Union oder Fehler (konfigurierbar).
- Farbmodi `vertex`, `texture`, `cad` → LDraw-Codes über `pyldraw3`-Farbtabelle.
- **Abnahme:** STEP-Würfel und STL-Würfel ergeben identische Grids; ein farbiges OBJ-Fixture liefert ein mehrfarbiges Modell.

### Phase 4 – Katalog und Whitelist
- `PartSpec`-Ableitung aus `pyldraw3`-Geometrie für brick/plate/slope/tile; JSON-Cache.
- `rebrickable`-Offline-Katalog für Namen, Verfügbarkeit, BrickLink-Mapping.
- Whitelist/Blacklist aus Config an legolization durchreichen; prüfen, ob legolization das nativ unterstützt – falls nicht: Upstream-PR.
- **Abnahme:** `mesh2brick catalog list --category slope` funktioniert offline; BOM zeigt Rebrickable-Namen.

### Phase 5 – Eigene Platzierungs-/Stabilitätserweiterungen (nur bei Bedarf)
- Benchmark aller legolization-Strategien auf den Fixtures (`docs/benchmarks.md`: Laufzeit, Teilezahl, Stabilität).
- Nur wenn Lücken messbar sind: eigene Strategie hinter `Placer`-Protocol, oder Upstream-PR.
- **Abnahme:** Benchmark-Tabelle vorhanden; Entscheidung „eigene Strategie ja/nein" als ADR.

### Phase 6 – Anleitungsqualität
- Eigenes PDF-Layout falls legolization-PDF nicht reicht: Deckblatt (Rendering, Teilezahl, Maße), BOM-Seiten, Schrittseiten mit Callouts, gedimmte Vorschritte, 1–4 Schritte/Seite, de/en.
- Submodelle als MPD-Submodels mit eigenen Schritten.
- **Abnahme:** PDF < 10 MB für den Hasen; visuelle Prüfung dokumentiert.

### Phase 7 – LLM-Schicht
- Anthropic-Client mit Tool-Use (`catalog_lookup`, `stability_check`, `render_preview`).
- Aufgaben `group_steps`, `write_step_text`, `choose_part`; Ausgaben immer gegen Katalog und Stabilität validiert, sonst Fallback auf deterministisches Ergebnis.
- Feedback-Store (SQLite), `mesh2brick feedback --rate 4 --note "..."`, Few-Shot-Einspeisung, Export für späteres Fine-Tuning.
- **Abnahme:** Pipeline mit `llm.enabled` true/false liefert beide gültige Ausgaben; Kosten pro Lauf geloggt.

### Phase 8 – Blender, Politur, v1.0
- `.blend` headless → glTF/OBJ → Ingest. `mesh2brick inspect` mit PNG-Vorschau. Doku vervollständigen, Beispielgalerie, `v1.0.0`.

---

## 6. Git und GitHub

- Repo initialisieren, erster Commit = Phase 0. Branch `main` geschützt; Arbeit auf `feat/<phase>-<thema>`, Merge per PR (für CI).
- Conventional Commits mit DCO-Sign-off (`git commit -s -m "feat: ..."`).
- GitHub: `gh auth status` prüfen, dann `gh repo create <owner>/mesh2brick --public --source=. --push`. Falls `gh` fehlt oder nicht angemeldet: anhalten und den Nutzer bitten – keine Tokens selbst erzeugen.
- Issues pro Phase mit den Abnahmekriterien als Checkliste; Release-Tags pro Phase mit CHANGELOG-Auszug.
- Upstream-PRs an `hbmartin/legolization` bzw. `hbmartin/pyldraw3` nur nach Freigabe durch den Nutzer; Entwurf (Branch + PR-Text) vorbereiten und in `docs/UPSTREAM.md` verlinken.

---

## 7. Inhalt von `CLAUDE.md` (in Phase 0 anlegen)

```
# mesh2brick – working agreement
- Read SPEC.md before any non-trivial change; it is the source of truth.
- Keep docs/STATUS.md current: current phase, done, next, open questions (in plain language, no jargon).
- Plan before coding: for any change > 1 file, write the plan in the PR description.
- Run `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` before every commit.
- License is GPL-3.0-or-later. Every source file has an SPDX header. Adapted third-party code keeps its
  copyright notice and states source, license and commit hash. Record every dependency in docs/THIRD_PARTY.md.
- Only backends/ may import legolization, pyldraw3 or rebrickable.
- Upstream first: generally useful fixes go to the upstream project as a PR draft (ask before opening).
- Any architectural decision gets an ADR in docs/adr/.
- Ask before: adding dependencies > 50 MB, changing public CLI flags, deleting fixtures, opening upstream PRs.
- Code/comments/commits in English. User docs in German and English.
- Small commits, conventional commit messages, DCO sign-off, one logical change per commit.
- Prefer pure functions and frozen dataclasses; no global state; no hidden I/O in core modules.
- LDraw facts: 1 stud = 20 LDU, brick = 24 LDU, plate = 8 LDU, -Y is up. Validate part IDs against the library.
- Verify your own work visually: render a PNG preview after every pipeline change and look at it.
```

---

## 8. Arbeitsweise für Claude Code (Vibe-Coding-Modus)

Der Nutzer ist Product Owner. Er kann sagen, ob ein Ergebnis gut aussieht, ob die Anleitung verständlich ist und welche Modelle er bauen will. Er kann **nicht** beurteilen, welcher Voxelisierungsalgorithmus oder welche Stabilitätsformulierung richtig ist. Daraus folgt:

1. **Fachentscheidungen selbst treffen.** Algorithmus, Datenstruktur, Bibliothekswahl: entscheiden, als ADR begründen (3–5 Sätze, verständlich), weitermachen. Nicht fragen „Soll ich A oder B nehmen?", sondern „Ich habe A gewählt, weil …; wenn du X wichtiger findest, sag Bescheid".
2. **Nur Ziel- und Geschmacksfragen stellen.** Beispiele: Welche Modelle sind die ersten echten Testfälle? Wie detailliert sollen Anleitungen sein? Welche Farben? Ist die PDF-Optik gut? Solche Fragen gesammelt am Session-Ende in `docs/STATUS.md` → „Fragen an dich", maximal drei, jeweils mit Standardannahme, die gilt, wenn keine Antwort kommt.
3. **Ergebnisse zeigen, nicht beschreiben.** Nach jeder Phase ein PNG in `docs/gallery/` und ein Zwei-Satz-Fazit in `docs/STATUS.md`, das ein Laie versteht („Der Hase hat jetzt 412 Teile, steht stabil, die Ohren wurden mit Slopes abgerundet").
4. **Selbst prüfen.** Tests für Geometrie zuerst; Vorschaubilder ansehen; LDraw-Dateien mit LDView-CLI öffnen, wenn verfügbar; bei Unsicherheit über eine LEGO-Konvention die LDraw-Dokumentation oder den legolization-Quellcode lesen, nicht raten.
5. **Lücken ehrlich benennen.** Wenn etwas nicht funktioniert oder legolization eine Grenze hat, steht das in `docs/STATUS.md` unter „Bekannte Einschränkungen", mit Einschätzung: Upstream-Fix / eigener Code / akzeptieren.
6. **Benchmarks pflegen.** `docs/benchmarks.md` bei jeder Änderung an Voxelisierung, Backend-Konfiguration oder eigenen Strategien.
7. **Nutzerkontext.** Der Nutzer entwickelt in Python, nutzt `uv`, GitHub und Claude Code regelmäßig; Testmodelle kommen aus Fusion 360 (STEP/3MF) und aus dem 3D-Druck-Umfeld (STL). Kurze Rückfragen genügen.

---

## 9. Definition of Done (v1.0)

- `uv run mesh2brick convert model.step --config mesh2brick.yaml` erzeugt `.mpd`, drei BOM-Formate und ein PDF in unter 5 Minuten für ≤ 2000 Teile auf einem Laptop.
- Alle Fixtures: zusammenhängend, stabil (oder dokumentiert nicht-stabil), in LDView/Studio fehlerfrei zu öffnen.
- Testabdeckung `src/` ≥ 80 %, CI grün, Dokumentation de/en, Lizenz- und Upstream-Übersicht aktuell.
