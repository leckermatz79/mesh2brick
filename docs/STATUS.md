# Projektstatus

Stand: 2026-11-10 · **1.6.1 – Bewertungsskala dokumentiert, damit ist 1.x abgeschlossen** ([#29](https://github.com/leckermatz79/mesh2brick/issues/29), ROADMAP Punkt 6) · davor Roadmap 7 (Aufräumen, [#30](https://github.com/leckermatz79/mesh2brick/issues/30)) und 1.6.0 (bessere Teileschätzung, [Release](https://github.com/leckermatz79/mesh2brick/releases/tag/v1.6.0)) · Nächster Schritt: **deine Entscheidung, mit welchem 2.0-Punkt es losgeht** (siehe „Als Nächstes“)
Repo: https://github.com/leckermatz79/mesh2brick (öffentlich) · Plan: [PLAN.md](PLAN.md) · Messwerte: [benchmarks.md](benchmarks.md) · [Beispielgalerie](gallery/README.md) · Was 1.0 kann: [CHANGELOG.md](../CHANGELOG.md)

## Fazit in zwei Sätzen

- **Die Bewertungsskala steht jetzt da, wo man sie braucht:** `mesh2brick feedback --help` und beide READMEs sagen „1 bis 5 Sterne, 5 = am besten“ (1 = unbrauchbar, 3 = in Ordnung).
- **Damit ist 1.x fertig:** Große Modelle gehen (Größe in cm, harte Zeitgrenze, geprüfte Schritte, PDFs unter 10 MB, verlässliche Teileschätzung). Mit 2.0 fange ich erst an, wenn du die Reihenfolge entschieden hast.

## Erledigt (1.6.1, ROADMAP Punkt 6)

- **Hilfe:** `mesh2brick feedback --help` nennt die Skala zweimal, in der Beschreibung („The scale is 1 to 5 stars, 5 = best“) und bei `--rate` („Stars from 1 to 5, 5 = best (1 = unusable, 3 = okay)“, dazu: 4 oder 5 machen den Lauf zum Beispiel für spätere Läufe). Ein Test prüft das unabhängig von der Breite des Terminals.
- **README.md und README.de.md** nennen die Skala beim Befehl und im Text.
- **SPEC §8, neue Regel 8 (von dir):** Ich darf Release-Seiten für schon vorhandene Tags anlegen; Merge, Tags und alles Upstream bleiben bei dir.

| Abnahme (Issue #29) | Ergebnis |
|---|---|
| `mesh2brick feedback --help` nennt die Skala (1–5, 5 = am besten) | **ja** |
| README.md und README.de.md nennen sie | **ja** |
| Tests grün, ruff/mypy sauber | **ja** |

## Erledigt (Roadmap 7, Aufräumen)

- **Alte Release-Seiten:** v0.0.0 bis v0.7.0 haben jetzt je eine [Release-Seite](https://github.com/leckermatz79/mesh2brick/releases) mit ihrem CHANGELOG-Abschnitt, als Vorabversion markiert (Phasen vor 1.0); 1.6.0 bleibt die aktuelle Version. Das Skript dafür liegt in `out/releases/create-old-releases.sh` (nicht im Repo).
- **trimesh-Bericht:** war schon erledigt ([#2669](https://github.com/mikedh/trimesh/issues/2669)).
- **Veralteter Eintrag entfernt:** Das legolization-Issue zur Schrittplanung (Entwurf #15–17) stand noch unter „Offene Kleinigkeiten“, ist aber seit 2026-11-09 eingereicht ([#99](https://github.com/hbmartin/legolization/issues/99), noch ohne Antwort).
- **Der Test, der im Schlafmodus gescheitert ist** (KI-Schicht an und aus beim Herz), hängt nicht mehr an der Uhr. Er hat das Herz zweimal unabhängig gebaut und die Dateien verglichen. Beide Läufe sind aber nur gleich, solange keine Zeitgrenze greift: Die Stabilitätsrechnung bricht einen Lösungsversuch nach 1 bzw. 5 Sekunden ab, und diese Uhr läuft auf dem Mac auch im Schlaf weiter (die Fristen von mesh2brick selbst nicht). Jetzt bauen beide Läufe auf derselben Platzierung auf; geprüft wird, was die KI-Schicht ändert, und das ist genau der Zweck des Tests. Einen „Timing“-Test brauchte es nicht: Nur dieser eine Test vergleicht zwei unabhängige Platzierungen.

## Erledigt (1.6.0, ROADMAP Punkt 5)

- **Erst geprüft, ob deine Idee reicht (ausgehöhltes Gitter plus Plattenanteil):** Nur das ausgehöhlte Gitter zu füllen, macht es bei Kästen schlechter (Würfel Faktor 3,1 daneben). Den Ausschlag gibt eine andere Stelle, die ich an den gespeicherten Ergebnissen von 1.5 und mit legolizations eigener Messung gefunden habe (Zahlen in [benchmarks.md](benchmarks.md), „Part estimate“, Begründung in ADR 0019):
  - legolization rechnet in Plattenhöhe. Einen Stein setzt es nur, wo drei Platten übereinander durchgehend gleichfarbig gefüllt sind, sonst Platten. Das bilde ich jetzt genau nach (die Aushöhlung ist Zelle für Zelle dieselbe wie bei legolization; ein Test prüft das). Damit stimmt schon die erste Kachelung: zwei Körper 236 = 236 Teile.
  - Die großen Abweichungen entstehen danach: Was nach dem Kacheln nicht zusammenhängt, baut legolization aus kleinen Platten neu. Burg: 581 Teile in 20 losen Gruppen, danach 1.653. Würfel: 910 in 5 Gruppen, danach 1.952.
  - Wo das passiert, sieht man dem Modell vorher an: Flächen, die nur einen Stein hoch sind und weder darüber noch darunter etwas haben (Burghof, Duos Sockel, eine Tischplatte), werden immer drei Lagen kleiner Platten. Dünne Böden hohler Körper werden auch neu gebaut. Bis etwa 30 × 30 Noppen mischt legolization sie mal zu kleinen Steinen zurück, mal bleiben sie Platten (vorher nicht absehbar, an fünf hohlen Testkästen nachgemessen); breitere blieben immer Platten.
- **Die neue Schätzung** zählt diese Flächen extra, statt alles mit festen Faktoren zu multiplizieren. Wo legolizations Ergebnis selbst schwankt (hohle Böden bis etwa 30 × 30 Noppen), ist der Bereich breiter, sonst schmal.
- **Zeithinweis** („recommended: --time 20min“ ab 2.000 erwarteten Teilen): Er erscheint bei den Testmodellen nur noch bei Duo mit 48 Noppen (erwartet 2.342). Hinweis zu deiner Vorgabe: In 1.5 erschien er außer bei Duo 48 auch bei den beiden Würfeln und beim Texturwürfel (geschätzt 2.246). Die werden aber in gut 4 Minuten fertig und brauchen ihn nicht; jetzt fehlt er dort. Neue Modelle mit Hinweis gibt es nicht.

| Abnahme (Issue #28) | Ergebnis |
|---|---|
| 15 von 15 Testläufen im angezeigten Bereich | **ja** (1.5: 14 von 15, die Burg lag daneben) |
| Bereich im Mittel enger als heute (Faktor 2,2) | **ja**: Faktor 1,78; 12 von 15 Läufen 1,6, Duo 48 Faktor 2,0, zwei Körper 3,9 |
| `inspect` nicht spürbar langsamer | **ja**: Schätzung 0,3–43 ms statt 0,1–33 ms; `inspect` dauert 2,5–15 s |
| Ersatzrechnung für sehr große Gitter bleibt oder wird begründet ersetzt | **ersetzt, begründet**: Sie zählt jetzt die Schale statt des vollen Körpers (ab 500.000 Plattenzellen). Die Rechnung läuft nur noch über die Schale, deshalb rechnen viel größere Modelle genau, etwa eine Kugel mit 128 Noppen in 1,3 s. |
| Keine Änderung an Platzierung, Schritten oder PDF | **ja**, nur `voxel/estimate.py` und die Ausgabe von `inspect`/`convert` |
| Gegenprobe an Daten, auf die nichts abgestimmt ist | **ja**: Duo bei 20 cm (799 Teile; 536–871), Rakete bei 30 cm (376; 341–541) und alle Testmodelle (Tisch, zweifarbiger Kasten, fünf hohle Kästen) liegen im Bereich |

## Schätzung 1.6 (in Klammern 1.5)

| Modell | Teile | Schätzung | Bereich | Im Bereich |
|---|---|---|---|---|
| Herz | 12 | 12 (16) | 10–16 (11–24) | ja |
| L-Winkel | 153 | 153 (213) | 130–207 (148–328) | ja |
| Rakete (`.blend`) | 263 | 299 (291) | 254–404 (202–448) | ja |
| Torus | 552 | 599 (515) | 509–809 (356–792) | ja |
| Zwei Körper (STEP) | 606 | 633 (541) | 300–1.154 (374–832) | ja |
| Hase | 873 | 670 (658) | 570–905 (455–1.012) | ja |
| Duo (32, nur lokal) | 1.025 | 907 (757) | 753–1.224 (524–1.164) | ja |
| Fliegenpilz | 1.239 | 1.281 (1.222) | 1.089–1.729 (846–1.880) | ja |
| Kugel | 1.499 | 1.587 (1.746) | 1.349–2.142 (1.209–2.686) | ja |
| Vertex-Modell (PLY) | 1.519 | 1.587 (1.747) | 1.349–2.142 (1.210–2.688) | ja |
| STEP-Burg (`--config`) | 1.657 | 1.718 (602) | 1.384–2.242 (417–926) | **ja** (1.5: nein) |
| STEP-/STL-Würfel | 1.952 | 1.930 (2.246) | 1.548–2.513 (1.555–3.456) | ja |
| Texturwürfel | 2.280 | 1.940 (2.246) | 1.556–2.526 (1.555–3.456) | ja |
| Duo (48, nur lokal) | 2.308 | 2.342 (2.423) | 1.740–3.478 (1.678–3.728) | ja |

Die Teilezahlen sind die des 1.5-Laufs; 1.6 ändert am Bauen nichts. Neu gerechnet ohne Umwandlung: `uv run python scripts/benchmark_estimate.py --results out/release-1.5` (Sekunden).

## Als Nächstes

Was kommt und in welcher Reihenfolge, steht in [ROADMAP.md](../ROADMAP.md) (von dir, 2026-11-07). Die Punkte 1–7 haben je ein [Issue mit Label `roadmap`](https://github.com/leckermatz79/mesh2brick/issues?q=label%3Aroadmap) (#24–#30) mit Abnahmekriterien, wie die Phasen.

**1.x – große Modelle möglich machen** (keine neuen Steinarten):

1. ~~Roadmap 1 – Größe in Zentimetern~~ ([#24](https://github.com/leckermatz79/mesh2brick/issues/24)): **fertig**.
2. ~~Roadmap 2 – harte Zeitgrenze~~ ([#25](https://github.com/leckermatz79/mesh2brick/issues/25)): **fertig**.
3. ~~Löserreihenfolge + Dachsteine wieder an~~ (ROADMAP Punkt 8, [#34](https://github.com/leckermatz79/mesh2brick/issues/34)): **fertig in 1.3.0**.
4. ~~Roadmap 3 – Stabilitätsprüfung auch für große Modelle~~ ([#26](https://github.com/leckermatz79/mesh2brick/issues/26)): **fertig in 1.4.0**.
5. ~~Roadmap 4 – kleinere PDFs~~ ([#27](https://github.com/leckermatz79/mesh2brick/issues/27)): **fertig in 1.5.0**.
6. ~~Roadmap 5 – bessere Teileschätzung in `inspect`~~ ([#28](https://github.com/leckermatz79/mesh2brick/issues/28)): **fertig in 1.6.0**, siehe oben.
7. ~~Roadmap 6 – Bewertungsskala dokumentiert~~ ([#29](https://github.com/leckermatz79/mesh2brick/issues/29)): **fertig in 1.6.1**, siehe oben.
8. ~~Roadmap 7 – Aufräumen~~ ([#30](https://github.com/leckermatz79/mesh2brick/issues/30)): **fertig**, siehe oben (alte Release-Seiten, Test ohne Uhr-Abhängigkeit).

**1.x ist abgeschlossen.** Alle sieben Punkte sind fertig.

**2.0 – Formtreue: Der erste Punkt braucht deine Entscheidung zur Reihenfolge.** Zur Wahl stehen ROADMAP 8 (mehr Dachsteine) oder ROADMAP 9 (Tiles) zuerst; ich fange keinen 2.0-Punkt an, bevor du entschieden hast. Was ich dazu weiß (noch nichts gemessen):

- **8 – mehr Dachsteine:** Der größte sichtbare Schritt bei runden Formen (Duos Flügel, Fliegenpilz-Hut), heute setzt legolization nur wenige (14 beim Hasen; über alle Testmodelle sind nur 10 von 130 von außen sichtbar). Dafür muss die Platzierung selbst beeinflusst werden. Hängt das an einer Änderung in legolization, steht die offene Frage „Fork oder Warten“ bei legolization an; die entscheidest du, wenn es so weit ist (vereinbart am 2026-11-07).
- **9 – Tiles:** Kleiner und eher eigener Code. legolization kann schon jede freiliegende obere Platte durch eine glatte Fliese ersetzen (abschaltbar, heute aus); ROADMAP 9 will das nur dort, wo das Modell wirklich glatt sein soll (Oberseiten, Sockel, Augen).

Danach folgen runde Teile, SNOT, Farbverfügbarkeit bei der Platzierung und `choose_part` (Roadmap 10–13). Upstream: Antworten auf legolization #88/#89, #90/#91 und #99 sowie trimesh #2669 abwarten.

## Bekannte Einschränkungen

| Was | Einschätzung |
|---|---|
| KI-Texte können plausibel klingen und trotzdem ungenau sein (z. B. „links“ statt „hinten“). Die Prüfung erkennt falsche Teile und Mengen, aber keine falsche Richtung; Claude sieht nicht jedes Schrittbild. | akzeptieren; mit Bewertungen und Notizen nachsteuern |
| Die KI legt selten Schritte zusammen: Die kleinen hat mesh2brick schon vorher zusammengelegt, und die übrigen Nachbarn verdecken sich meist gegenseitig. | akzeptieren; der Nutzen liegt in Abschnitten und Texten |
| Für Claude-Modelle, deren Preise mesh2brick nicht kennt, gilt die Kostengrenze nicht (der Lauf sagt das). | Preistabelle bei neuen Modellen ergänzen |
| Große Modelle prüfen ihre Zwischenstände in der Zeit, die nach der Platzierung bleibt. In 5 Minuten schaffen die größten Testmodelle 40–87 % (Würfel, Burg, Vertex-Modell, Kugel); die ungeprüften stehen oben im Modell. Deckblatt und Kommandozeile sagen, wie viele geprüft sind. | `--time 20min` prüft alle; kein eigener Code nötig |
| Während der Prüfung rechnet mesh2brick auf allen Kernen bis auf einen (bis zu einige Minuten, Lüfter hörbar). | von dir so gewollt (2026-11-09) |
| Kleine Modelle (bis 500 Teile) nutzen weiter legolizations Suche; die geprüfte Schichtfolge wäre auch dort schneller und bräuchte seltener eine Hand (Rakete: 0 statt 11 Schritte). | von dir so entschieden (2026-11-09); Wiedervorlage bei 2.x Punkt 17 |
| Hängen mehrere vorher zusammengesteckte Teile aneinander, wird ein Schritt größer (Kugel bei 32 Noppen: einmal 18 Teile, sonst meist höchstens 10). | selten; eigener Code, falls es stört |
| Bei kleinen Modellen übernimmt legolization die Reihenfolge, bei großen die geprüfte Schichtfolge. Wo die Stabilitätsrechnung „braucht Stütze“ meldet, steht im PDF „Halte das Modell fest“. | akzeptiert |
| „Teile weglassen“ gilt fürs ganze Modell, nicht pro Farbe. | Upstream #9 (nach #8) |
| 1×1-Stein und 1×1-Platte lassen sich weder weglassen noch aufteilen. Gibt es sie in einer Modellfarbe nicht, meldet die Teileliste das. | selten; akzeptiert |
| legolization setzt nur Platten bis 2×8. Größere Platten würden Teile sparen. | Upstream-Kandidat #10 |
| Reine Computer-Grundfarben landen teils auf Nachbarfarben (#FF0000 → „Reddish Orange“). | von dir als Farbmetrik akzeptiert |
| Bemalte Farben aus dem Slicer und Texturen in 3MF werden noch nicht gelesen. | bei Bedarf |
| Dachsteine sind an, aber legolization setzt nur wenige, und die meisten liegen innen in der hohlen Wand (10 von 130 sichtbar). | eigener Code in 2.0 (ROADMAP Punkt 8, zweiter Teil) |
| Voxelisieren, PDF und Vorschau werden nicht abgebrochen; für sie hält mesh2brick Zeit frei (20 s + 0,03 s pro Teil, gemessen reichte das überall). Auf einem viel langsameren Rechner kann die Umwandlung die Grenze um einen Teil der PDF-Zeit überschreiten; die Kommandozeile sagt das dann. | akzeptieren |
| Wird ein Modell an der Zeitgrenze abgeschnitten, hat es meist etwas mehr Teile (die letzte Optimierung spart Teile) oder ist im ungünstigsten Fall nicht auf Stabilität geprüft. Deckblatt und Kommandozeile sagen das. | mehr Zeit geben (`--set placement.time_limit_s=1200`); Upstream-Kandidat #5 |
| Der schnellere Rechenweg und das Mitlesen der Zwischenstände sind lokale Eingriffe in legolization (UPSTREAM #2 und #5). Ändert legolization diese Stellen, meldet mesh2brick das beim Start. | bei Upstream vorschlagen (#5), wenn #88/#89 Antwort haben |
| Große geschlossene Körper (Würfel, der die ganze 32-Noppen-Box füllt) brauchen für die Platzierung etwa 3 Minuten; den Rest der 5 Minuten verwenden sie für die Prüfung. Auf einem langsameren Laptop bleibt weniger für die Prüfung oder sie werden an der 5-Minuten-Grenze abgeschnitten (bestes stabiles Modell bis dahin), statt länger zu dauern. | Standard bleibt 32 Noppen |
| Der Texturwürfel liegt mit 9,6 MB knapp unter 10 MB; ein noch größerer geschlossener Körper bei 32 Noppen kann darüber liegen. Der Release-Benchmark warnt dann (kB pro Schritt). | akzeptieren; bei Bedarf 100 dpi für sehr große Modelle |
| Die Teileschätzung von `inspect` hängt an legolizations Verhalten. Bei hohlen Böden bis etwa 30 × 30 Noppen baut legolization den Boden mal aus Platten, mal aus kleinen Steinen; dort ist der Bereich breiter (zwei Körper: Faktor 3,9). Nach einem legolization-Update kann sie danebenliegen. | `convert` gibt die genaue Zahl; nach Updates `scripts/benchmark_estimate.py` laufen lassen |
| Spitze Formen werden mit `--size` etwas niedriger als gewünscht: Eine Spitze, die nicht einmal eine halbe Zelle füllt, fällt weg (dieselbe Regel wie bei allen dünnen Details). Rakete: 38,4 statt 40 cm, ihr fehlen oben 2 Lagen der Nasenspitze. Duo trifft die Höhe auf einen halben Stein genau. `inspect` zeigt die echte Höhe vorher. | akzeptieren; eigener Code (Größe nachregeln), falls es stört |
| `.blend`: Blender muss installiert sein. Die Tests mit echtem Blender laufen nur hier auf dem Mac; die automatischen Tests auf GitHub nutzen einen Blender-Ersatz. Verknüpfte Bibliotheken müssen vom Ordner der Datei aus erreichbar sein. | akzeptieren |
| glTF mit Draco-Kompression kann trimesh nicht lesen. | bei Bedarf; in Blender ohne Kompression exportieren |

## Umgebung (gut zu wissen)

- Die Python-Umgebung liegt außerhalb von Nextcloud (`.venv` ist ein Symlink nach `~/.local/share/venvs/mesh2brick`).
- Die LDraw-Teilebibliothek liegt in `~/Library/Caches/pyldraw3`, der Zwischenspeicher für Teilebeschreibungen in `~/Library/Caches/mesh2brick`. `samples/` (Duo) ist von Git ausgeschlossen.
- STEP braucht einmalig `uv sync --extra step`, die KI-Schicht `uv sync --extra llm` (beides zusammen: `uv sync --extra step --extra llm`) und `ANTHROPIC_API_KEY`.
- Der Bewertungsspeicher liegt in `~/Library/Application Support/mesh2brick/feedback.sqlite3` (anderer Ordner mit `MESH2BRICK_DATA_DIR`).
- Die Galeriebilder der PDF-Seiten entstehen mit `pdftoppm` (Homebrew-Paket poppler).
- Lange Messläufe brauchen einen offenen Deckel: Zugeklappt auf Akku schläft der Laptop, und die Prüfprozesse bekommen kaum Rechenzeit (so geschehen beim ersten 1.4-Lauf; die Duo-Fälle wurden wiederholt).
- Blender 4.0.1 liegt unter `/Applications/Blender.app` und wird automatisch gefunden. Ein anderes Blender: `MESH2BRICK_BLENDER=/pfad/zu/blender`.
- Galerie und Abnahme neu erzeugen: `uv run python scripts/benchmark_release.py --out out/release` (dauert etwa 30 Minuten), dann `uv run python scripts/make_gallery.py --results out/release`.

## Deine Entscheidungen

| Datum | Frage | Entscheidung |
|---|---|---|
| 2026-11-01 | Erster echter Testfall? | Duo (Eule aus `samples/`), **nur lokal**: nicht im Repo, nicht in der Galerie. |
| 2026-11-01 | Typische Modellgröße? | **32 Noppen** auf der längsten Achse (≈ 26 cm) als Standard, 48 erst später. |
| 2026-11-01 | LeoCAD für PDF-Schrittbilder installieren? | **Ja**, per Homebrew zu Beginn von Phase 2. Leider nicht möglich (s. o.). |
| 2026-11-01 | Fehlerbericht #2 bei legolization einreichen? | **Ja**, plus PR-Entwurf für das Zeitlimit; mit Hinweis, dass das Problem in einem Vibe-Coding-Projekt aufgefallen ist. Erledigt: Issue #88, Draft-PR #89. |
| 2026-11-01 | Wie lange darf eine Umwandlung dauern? | **5 Minuten.** Phase 2: Duo unter 5 Minuten als Zielmarke, Hebel per Benchmark wählen. Erreicht: 110 s (mit KI-Schicht 161 s). |
| 2026-11-01 | Manuelle Prüfung der `.ldr` in BrickLink Studio? | **Ja, Screenshot kommt später.** Bis dahin gilt der strenge Wieder-Einlese-Test als Prüfung. |
| 2026-11-01 | LeoCAD manuell installieren und nutzen? | **Nein.** Schrittbilder kommen vom eigenen Renderer. |
| 2026-11-01 | Schichtschritte für große Modelle (> 500 Teile)? | **Ja**, in Ordnung. |
| 2026-11-01 | STEP-Zusatzpaket mit 70 MB (über der 50-MB-Regel)? | **In Ordnung.** Ein vollständiger CAD-Kern rechtfertigt die Größe, er wird nur bei Bedarf installiert. Die Rückfrage war richtig: So soll die 50-MB-Regel funktionieren. |
| 2026-11-01 | Farben aus dem Modell automatisch übernehmen? | **Ja.** Einfarbig bleibt per Config erreichbar (`color.mode: single`). |
| 2026-11-01 | Gängige LEGO-Farben statt exakter Farbtöne? | **Ja.** Eine Anleitung, deren Steine man nicht kaufen kann, ist wertlos. Für Spezialfälle gibt es `color.palette: all`. |
| 2026-11-01 | Reines #FF0000 wird „Reddish Orange“ | **Kein Bug, sondern Farbmetrik.** Optional in Phase 4: kleine Ausnahmetabelle für reine Primärfarben. Erwähnen, nicht priorisieren. |
| 2026-11-01 | Upstream-Vorschlag „erlaubte Teile direkt angeben“ (#8) einreichen? | **Ja, einreichen.** Derselbe Fall wie #88/#89, und den lokalen Patch will man nicht dauerhaft pflegen. Im Issue kurz auf #89 verweisen, weil der Maintainer dort noch nicht reagiert hat, damit er den Zusammenhang sieht. Erledigt: Issue #90, Draft-PR #91. |
| 2026-11-01 | Steine, die es in einer Farbe nicht gibt, automatisch ersetzen? | **Ja, als Zwischenlösung** (1×8 → 2× 1×4, danach Stabilitätsprüfung). Sauber wäre, die Farbverfügbarkeit schon bei der Platzierung zu kennen (hängt am selben Upstream-Thema). **Phase 5 vergleicht beides im Benchmark an Duo:** Aufteilen danach gegen Einschränken davor. |
| 2026-11-01 | Manuelle Prüfung in BrickLink Studio | **Erledigt** (Duo, lokal): keine Überlappungen, keine Duplikate, 0 Stabilitätsprobleme, 31 Clutch-Hinweise (Flügel, Füße). Import hängt auf dem Mac, Datei → Öffnen geht (README). Schrittgrößen → Phase 6. |
| 2026-11-07 | Schritte pro Seite und Optik der Anleitung? | **2 Schritte pro Seite, Optik bleibt so.** |
| 2026-11-07 | Teile unter Überhängen: im selben Schritt oder eigener Mini-Bauabschnitt? | **Im selben Schritt** (vorher in der Hand zusammenstecken, gelbes „zuerst“-Feld). |
| 2026-11-07 | Farbnamen in der deutschen Anleitung? | **Englisch plus deutscher Name in Klammern** („Bright Green (Hellgrün)“). Umgesetzt in Phase 7. |
| 2026-11-07 | KI-Schicht standardmäßig einschalten? | **Nein**, bleibt aus (einschalten mit `--set llm.enabled=true`). |
| 2026-11-07 | Anrede in den Schritttexten? | **„du“** („Setze den Hut auf den Stiel.“). |
| 2026-11-07 | Bauabschnitte auf dem Deckblatt? | **Ja**, als Übersicht mit Seitenzahlen. Umgesetzt im Nachtrag zu Phase 7. |
| 2026-11-07 | Phase 7: Zugang zur Anthropic-API? | **`ANTHROPIC_API_KEY` ist gesetzt.** Für Entwicklung und Messungen dieser Phase wurden insgesamt etwa 1,05 $ verbraucht. |
| 2026-11-07 | Fehlerbericht an trimesh (#14) einreichen? | **Ja.** trimesh ist groß und aktiv gepflegt, da kommen Antworten. Wie bei legolization: Text überfliegen, dann den fertigen Befehl ausführen. Erledigt: [Issue #2669](https://github.com/mikedh/trimesh/issues/2669). |
| 2026-11-07 | Was nach 1.0 zuerst? | **[ROADMAP.md](../ROADMAP.md)**: 1.x = große Modelle (Größe in cm, harte Zeitgrenze, Stabilitätsprüfung, PDF-Größe, Schätzung), 2.0 = Formtreue (Dachsteine, Tiles, Rundungen, SNOT), 2.x = Robustheit und Anleitung. Grund: Wer 40 cm will, bekommt heute gar nichts. 2.0 ist vor allem für Familienbauten; ein persönliches Teilelager ist nicht Teil des Plans; Fork oder Warten bei legolization entscheidest du, wenn der erste 2.0-Punkt daran hängt. |
| 2026-11-07 | Eigenes Modell in der Galerie? | **Duo nein.** Ein selbst entworfenes Fusion-Modell wäre das beste Schaufenster (echtes CAD-Teil statt Testkörper). Es gibt keins (Fusion lässt sich hier nicht ohne Oberfläche steuern), also bleibt die Galerie bei den Testmodellen. |
| 2026-11-07 | Roadmap 1: Was meint „30 cm“? | **Die Höhe.** So denkt man über eine Figur; die längste Kante bleibt über `target_studs` (`--size 40studs`) erreichbar. |
| 2026-11-07 | Eigene kurze Option für die Größe? | **Ja, `--size 30cm`**, versteht auch `300mm` und `40studs`; `--set input.target_cm=30` tippt niemand gern zweimal. Umgesetzt; in der Config heißt der Wert `target_height_cm`, damit klar ist, dass er die Höhe meint. |
| 2026-11-07 | Große Modelle automatisch länger rechnen lassen? | **Nein, aber ein Hinweis.** Vorhersehbares Verhalten ist wichtiger: 5 Minuten sind 5 Minuten. `inspect` und der Start von `convert` sagen ab rund 2.000 geschätzten Teilen „expected about 3,905 parts; recommended: --time 20min“; du entscheidest. Umgesetzt. |
| 2026-11-07 | Kurze Option für die Zeit? | **Ja, `--time 20min`** (auch `90s`, `1h`), aus demselben Grund wie `--size`: Was man beim Ausprobieren tippt, verdient eine kurze Option. Umgesetzt. |
| 2026-11-07 | Schnelleren Rechenweg bei legolization vorschlagen? | **Ja, nach deinem Blick auf den Text.** Er benennt die Ursache statt des Symptoms und ist damit wertvoller als unser Zeitlimit-PR. Kommentar an #89, Verweis in #88. **Erledigt** von dir: [Kommentar an #89](https://github.com/hbmartin/legolization/pull/89#issuecomment-6712391855), [Verweis in #88](https://github.com/hbmartin/legolization/issues/88#issuecomment-6712393969). |
| 2026-11-07 | Vor Roadmap 3: Ist der Slope-Hänger dasselbe Crossover-Problem? | **Gemessen:** nein, ein Simplex-Problem, aber derselbe Ausweg hilft (Hase mit Dachsteinen 147 s → 17,5 s). Vorschlag: Löserreihenfolge zuerst. |
| 2026-11-07 | Reihenfolge nach der Slope-Messung? | **Erst Löserreihenfolge + Dachsteine wieder an als 1.3.0, dann Roadmap 3.** Vorher „Simplex 1 s, dann Innere-Punkte-Löser“ messen; kleine Modelle dürfen nicht spürbar langsamer werden, die 5-s-Grenze pro Versuch bleibt. Dachsteine nur standardmäßig an, wenn alle Testmodelle stabil sind und höchstens die doppelte Zeit brauchen. ROADMAP Punkt 8 ist in die 1.x-Liste gerückt; mehr Dachsteine setzen bleibt in 2.0. |
| 2026-11-09 | Kleine Modelle auch auf die geprüfte Schichtfolge umstellen? | **Nein**, bis 500 Teile bleibt legolizations Suche wie in 1.3. Zum Vergleich die Rakete beide Male als PDF (Befehle unter „Offene Kleinigkeiten“). **Wiedervorlage bei 2.x Punkt 17** (geometrische Baugruppen). |
| 2026-11-09 | Alle Kerne für die Prüfung? | **Ja, alle bis auf einen.** Keine Einstellung dafür. |
| 2026-11-09 | legolization-Issue zu den drei Funden einreichen? | **Ja**, nach deinem Blick auf den Text; mit Halbsatz-Verweis auf #88/#89 (ergänzt). Befehl unter „Offene Kleinigkeiten“. |
| 2026-11-09 | Schrittbilder großer Modelle: schon gebaute Teile ohne Fugen? | **Ja, aber nur für große Modelle** (über 500 Teile), dazu 110 dpi und die sparsamere Farbpalette; kleine Modelle bleiben wie 1.4. Gewählt auf einer Vergleichsseite (wie 1.4 / unsichtbar sparsamer / ohne Fugen). |
| 2026-11-10 | Dürfen die Würfel den Zeithinweis verlieren (Roadmap 5)? | **Ja.** Der Hinweis bleibt an die Schwelle von 2.000 erwarteten Teilen gebunden. Die Würfel werden in gut vier Minuten fertig, und ein knappes Zeitbudget führt seit 1.4 nur zu weniger geprüften Zwischenständen, nicht zum Abbruch. |
| 2026-11-10 | Welcher 2.0-Punkt zuerst: ROADMAP 8 (mehr Dachsteine) oder 9 (Tiles)? | **Erst 9 (Tiles), dann 8.** Reihenfolge in 2.0: 9, 8, 10, 11, 12, 13. Grund: Tiles brauchen keine Änderung an der Platzierung und keine Upstream-Antwort. [ROADMAP.md](../ROADMAP.md) ist angepasst. |

## Fragen an dich

Keine offenen Fragen (die Reihenfolge in 2.0 ist entschieden: erst Tiles, dann Dachsteine).

## Offene Kleinigkeiten

- **Rakete im Vergleich** (Wiedervorlage bei 2.x Punkt 17): legolizations Suche (Standard, mit blauen Baugruppen) gegen die geprüfte Schichtfolge mit Mini-Vorbauten:
  `uv run mesh2brick convert tests/fixtures/rocket.blend -o out/rocket-suche`
  `uv run mesh2brick convert tests/fixtures/rocket.blend -o out/rocket-schichten --set steps.sequencing=checked-layers`
  Danach `out/rocket-suche/rocket.pdf` und `out/rocket-schichten/rocket.pdf` nebeneinanderlegen (gemessen: 11 gegen 0 Schritte mit „Halte fest“).
