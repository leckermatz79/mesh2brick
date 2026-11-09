# Projektstatus

Stand: 2026-11-09 · **1.4.0 – Stabilitätsprüfung auch für große Modelle fertig** ([Release](https://github.com/leckermatz79/mesh2brick/releases/tag/v1.4.0)) ([#26](https://github.com/leckermatz79/mesh2brick/issues/26), ROADMAP Punkt 3) · davor 1.3.0 (Löserreihenfolge + Dachsteine) · Nächster Punkt: **Roadmap 4 – kleinere PDFs** ([#27](https://github.com/leckermatz79/mesh2brick/issues/27), [ROADMAP.md](../ROADMAP.md))
Repo: https://github.com/leckermatz79/mesh2brick (öffentlich) · Plan: [PLAN.md](PLAN.md) · Messwerte: [benchmarks.md](benchmarks.md) · [Beispielgalerie](gallery/README.md) · Was 1.0 kann: [CHANGELOG.md](../CHANGELOG.md)

## Fazit in zwei Sätzen

- **Große Modelle bekommen jetzt geprüfte Zwischenstände:** mesh2brick behält seine Schichtfolge mit den „zuerst“-Mini-Vorbauten und prüft danach jeden Zwischenstand, parallel auf allen Kernen bis auf einen. Bei keinem Testmodell muss man dann irgendwo festhalten; legolizations eigene Suche hätte beim Hasen 60, bei Duo 107 und beim Fliegenpilz 158 Schritte mit „Halte fest“ gebraucht, und das in 6–7 statt 1–2 Minuten.
- **Ehrlich dazu:** In 5 Minuten werden bis etwa 1.250 Teile alle Zwischenstände fertig, bei den größten Testmodellen 40–87 %; das Deckblatt sagt dann genau, wie viele, und `--time 20min` prüft alle.

## Erledigt (1.4.0, ROADMAP Punkt 3)

- **Erst gemessen, wie von dir verlangt.** Die neue Löserreihenfolge aus 1.3 allein verschiebt die 500er-Grenze nicht: legolizations Suche braucht für Duo 32 jetzt 346 s statt rund 400 s, nach der Platzierung bleiben in 5 Minuten aber nur etwa 195 s. Die Zeit geht fast ganz in eine Rückwärtssuche, die nach der ersten wackligen Stelle den ganzen Rest des Modells mit Komplettrechnungen neu plant (Hase: 331 von 385 s).
- **Deine vier Optionen gegeneinander gemessen** (Hase, Duo 32, Kugel, dazu Torus): a) inkrementell lohnt sich nicht (die übersprungenen Teile muss die nächste Rechnung nachholen), b) Teilmodelle planen schneller, behalten aber die wackligen Schritte der Suche, d) „jeder 4. Zwischenstand“ ist schnell, lässt aber drei Viertel ungeprüft. **Gewählt: c) parallel**, und zwar auf der bewährten Schichtfolge: ein Prüfer arbeitet sich warm von unten hoch, die anderen prüfen jeden Zwischenstand einzeln von oben; sie treffen sich in der Mitte (ADR 0017).
- **Die 500er-Grenze entscheidet nicht mehr, ob geprüft wird, das entscheidet die Zeit.** Bis 500 Teile bleibt legolizations Suche wie in 1.3 (wenn ihre geschätzte Zeit passt), darüber die geprüfte Schichtfolge. Reicht die Zeit nicht für alle Zwischenstände, behalten die geprüften ihr Ergebnis, und Kommandozeile und Deckblatt nennen die Zahl („Die Zeit hat gereicht, um 126 von 274 Zwischenständen … zu prüfen (vollständig die unterste von 27 Steinlagen)“, beim Würfel, dessen massiver Boden allein viele Schritte braucht). Die harte Zeitgrenze aus 1.2 bleibt: am Ende werden alle Prüfprozesse beendet.
- **Schritte, Mini-Vorbauten und Teilezahlen** sind bei allen Testmodellen genau wie in 1.3; neu ist nur das Prüfergebnis. Die Galerie habe ich deshalb nicht neu erzeugt.
- **Upstream:** drei Funde zu legolizations Schrittplaner (warme Neuprüfung nach Baugruppen, Zeitgrenze für warme Rechnungen, Kosten der Rückwärtssuche) stehen als fertiger Issue-Text in [UPSTREAM.md](UPSTREAM.md), Entwurf #15–17.

| Abnahme (Issue #26) | Ergebnis |
|---|---|
| Duo 32: alle Zwischenstände in 5 Minuten geprüft, Modell stabil | **ja**: alle 153 in 139 s, keiner wacklig, ein stabiles Stück |
| Duo 48: alle in `--time 20min`, oder dokumentiert, wie viele | **dokumentiert:** 217 von 324 (67 %) in 1.189 s, keiner wacklig, ein stabiles Stück. Die Platzierung braucht allein rund 10 der 20 Minuten, die Prüfung aller Zustände 12–15 Minuten (ohne Platzierung gemessen: alle 325 in 919 s); `--time 30min` sollte für alle reichen (geschätzt) |
| Alle Testmodelle bis 2.000 Teile: alle Zwischenstände unter dem 5-Minuten-Standard geprüft | **teilweise:** bis 1.239 Teile alle (Torus, Zwei-Körper, Hase, Fliegenpilz, dazu die kleinen); Kugel 87 %, Vertex-Modell 73 %, Burg 65 %, Würfel 46 %. Mit `--time 20min` alle |
| … keines wird instabil, Teilezahl gleich wie 1.3 | **ja**: alle stabil, aus einem Stück, gleiche Teile- und Schrittzahlen |
| Kleine Modelle nicht spürbar langsamer | **ja**: Herz 4 s (4), L-Winkel 29 s (30), Rakete 19 s (19) |
| „Halte das Modell fest“ dort, wo legolization Stütze meldet; Mini-Vorbau unverändert | **ja**: Hinweise kommen aus legolizations Stabilitätsrechnung (bei großen Modellen war keiner nötig); „zuerst“-Felder wie in 1.3 |
| Zeitgrenze bleibt hart; Rückfall auf Schichten sagt es wie bisher | **ja**; ohne Zeit für Prüfungen der Satz aus 1.3, bei Teilprüfung der neue Satz |
| Unit-Tests für Entscheidungslogik, Teil auf geprüftem Unterbau, Kragarm; Benchmark-Spalte „checked states“ | **ja** |
| Upstream-Kandidaten mit fertigem Text | **ja**, #15–17 |

## Messwerte 1.4 (in Klammern 1.3)

| Modell | Teile | Zeit | geprüfte Zwischenstände | Schritte mit „Halte fest“ | stabil |
|---|---|---|---|---|---|
| Herz | 12 | 4 s (4 s) | 7 von 7 | 0 | ja |
| L-Winkel | 153 | 29 s (30 s) | 37 von 37 | 1 (wie 1.3) | ja |
| Rakete (`.blend`) | 263 | 19 s (19 s) | 42 von 42 | 11 (wie 1.3) | ja |
| Torus | 552 | 36 s (25 s) | 74 von 74 (keine) | 0 | ja |
| Zwei Körper (STEP) | 606 | 166 s (156 s) | 83 von 83 (keine) | 0 | ja |
| Hase | 873 | 125 s (81 s) | 126 von 126 (keine) | 0 | ja |
| Duo (32, nur lokal) | 1.025 | 139 s (78 s) | 153 von 153 (keine) | 0 | ja |
| Fliegenpilz | 1.239 | 259 s (157 s) | 178 von 178 (keine) | 0 | ja |
| Kugel | 1.499 | 280 s (126 s) | 180 von 207 (keine) | 0 | ja |
| Vertex-Modell (PLY) | 1.519 | 281 s (141 s) | 155 von 212 (keine) | 0 | ja |
| STEP-Burg (`--config`) | 1.657 | 265 s (223 s) | 151 von 234 (keine) | 0 | ja |
| STEP-Würfel | 1.952 | 265 s (220 s) | 126 von 274 (keine) | 0 | ja |
| Texturwürfel | 2.280 | 266 s (231 s) | 130 von 327 (keine) | 0 | ja |
| Duo (48, nur lokal, 20 min) | 2.308 | 1.189 s (733 s, Stand 1.2) | 217 von 324 (keine) | 0 | ja |

„(keine)“: In 1.3 war bei diesen Modellen kein Zwischenstand geprüft. Große Modelle brauchen jetzt länger, weil sie die bisher ungenutzte Zeit für die Prüfung verwenden; keines geht über 281 s. Alle Zahlen: [benchmarks.md](benchmarks.md), Abschnitt „Scalable stability checks (Roadmap 3)“.

## Als Nächstes

Was kommt und in welcher Reihenfolge, steht in [ROADMAP.md](../ROADMAP.md) (von dir, 2026-11-07). Die Punkte 1–7 haben je ein [Issue mit Label `roadmap`](https://github.com/leckermatz79/mesh2brick/issues?q=label%3Aroadmap) (#24–#30) mit Abnahmekriterien, wie die Phasen.

**1.x – große Modelle möglich machen** (keine neuen Steinarten):

1. ~~Roadmap 1 – Größe in Zentimetern~~ ([#24](https://github.com/leckermatz79/mesh2brick/issues/24)): **fertig**, siehe oben.
2. ~~Roadmap 2 – harte Zeitgrenze~~ ([#25](https://github.com/leckermatz79/mesh2brick/issues/25)): **fertig**, siehe oben.
3. ~~Löserreihenfolge + Dachsteine wieder an~~ (ROADMAP Punkt 8, [#34](https://github.com/leckermatz79/mesh2brick/issues/34)): **fertig in 1.3.0**, siehe oben.
4. ~~Roadmap 3 – Stabilitätsprüfung auch für große Modelle~~ ([#26](https://github.com/leckermatz79/mesh2brick/issues/26)): **fertig in 1.4.0**, siehe oben.
5. **Roadmap 4 – kleinere PDFs** ([#27](https://github.com/leckermatz79/mesh2brick/issues/27), nächster Punkt): große geschlossene Körper (Würfel 20–23 MB, Burg 19 MB) auf unter 10 MB.
6. Roadmap 5 ([#28](https://github.com/leckermatz79/mesh2brick/issues/28)) – bessere Teileschätzung in `inspect` (15 von 15 im Bereich).
7. Roadmap 6 ([#29](https://github.com/leckermatz79/mesh2brick/issues/29)) – Bewertungsskala (1–5, 5 = am besten) in Hilfe und README.
8. Roadmap 7 ([#30](https://github.com/leckermatz79/mesh2brick/issues/30)) – Aufräumen: trimesh-Bericht (erledigt, [#2669](https://github.com/mikedh/trimesh/issues/2669)), optional alte Release-Seiten.

**Danach 2.0 – Formtreue:** mehr Dachsteine, Tiles, runde Teile, SNOT (Roadmap 8–13). Upstream: Antworten auf legolization #88/#89 und #90/#91 sowie trimesh #2669 abwarten.

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
| Große geschlossene Körper (Würfel, der die ganze 32-Noppen-Box füllt) brauchen für die Platzierung etwa 3 Minuten; den Rest der 5 Minuten verwenden sie für die Prüfung. Auf einem langsameren Laptop bleibt weniger für die Prüfung oder sie werden an der 5-Minuten-Grenze abgeschnitten (bestes stabiles Modell bis dahin), statt länger zu dauern. Ihre PDFs sind 20–23 MB groß. | Standard bleibt 32 Noppen; PDF-Größe: Roadmap 4 |
| Die Teileschätzung von `inspect` ist grob (Bereich etwa Faktor 2) und liegt bei dünnen, großen Platten zu niedrig. | `convert` gibt die genaue Zahl; Roadmap 5 |
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

## Fragen an dich

Zurzeit keine. Deine Antworten zu Roadmap 3 stehen unter „Deine Entscheidungen“.

## Offene Kleinigkeiten

- **Rakete im Vergleich** (Wiedervorlage bei 2.x Punkt 17): legolizations Suche (Standard, mit blauen Baugruppen) gegen die geprüfte Schichtfolge mit Mini-Vorbauten:
  `uv run mesh2brick convert tests/fixtures/rocket.blend -o out/rocket-suche`
  `uv run mesh2brick convert tests/fixtures/rocket.blend -o out/rocket-schichten --set steps.sequencing=checked-layers`
  Danach `out/rocket-suche/rocket.pdf` und `out/rocket-schichten/rocket.pdf` nebeneinanderlegen (gemessen: 11 gegen 0 Schritte mit „Halte fest“).
- **legolization-Issue** (Entwurf #15–17 in [UPSTREAM.md](UPSTREAM.md), Text in `out/upstream/legolization-step-planning.md`), nach deinem Blick auf den Text:
  `gh issue create --repo hbmartin/legolization --title "Step planning on large hollow models: where the time goes (measurements, two small fixes)" --body-file out/upstream/legolization-step-planning.md`
- **Ältere Release-Seiten** (v0.0.0 bis v0.7.0) fehlen weiterhin; die Tags existieren, v1.0.0 hat seine Seite (Roadmap 7, #30). Befehl für `v0.0.0`:
  `awk '/^## \[0.0.0\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md | gh release create v0.0.0 --prerelease --title "v0.0.0 – Phase 0: skeleton" --notes-file -`
