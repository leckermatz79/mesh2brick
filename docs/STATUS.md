# Projektstatus

Stand: 2026-11-11 · **Teilen am Flächenrand** ([#46](https://github.com/leckermatz79/mesh2brick/issues/46), deine Wahl B, noch kein Release) · davor 85-%-Regel ([#44](https://github.com/leckermatz79/mesh2brick/issues/44)) und **1.7.0 – Fliesen auf flachen Oberseiten** ([Release](https://github.com/leckermatz79/mesh2brick/releases/tag/v1.7.0)) · Nächster Schritt: **deine Abnahme an den Bildern von Burg und Duo** (Frage unten), dann Fliesen an und 2.0.0, danach ROADMAP 8
Repo: https://github.com/leckermatz79/mesh2brick (öffentlich) · Plan: [PLAN.md](PLAN.md) · Messwerte: [benchmarks.md](benchmarks.md) · [Beispielgalerie](gallery/README.md) · Was 1.0 kann: [CHANGELOG.md](../CHANGELOG.md)

## Fazit in zwei Sätzen

- **Mit dem Teilen am Flächenrand bekommen jetzt auch Burg und Duo ganze glatte Flächen:** Burghof, Mauerkronen, Turmdächer und Bergfried (171 Fliesen) und Duos Sockelring (56 Fliesen), jeweils mit einem gleichmäßigen Noppenrand außen statt Noppen-Inseln; beide bleiben ein stabiles Stück, Burg +10,1 %, Duo +5,5 % Teile.
- Die vier Kästen sind unverändert; ob dich das Bild überzeugt (dann Fliesen an und 2.0.0, sonst Variante A), entscheidest du (Frage unten).

## Erledigt (#46, Teilen am Flächenrand, noch kein Release)

- **Regel:** Ein Teil, dessen Oberseite nur teilweise auf einer flachen Fläche liegt (der Rest ragt über den Rand oder liegt unter einer Mauer bzw. einem Turm), wird an der Flächengrenze geteilt, bevor die 85-%-Regel greift: außen bleibt ein Stein (bzw. eine Platte) mit Noppen, innen Platte + Fliese auf der Höhe der Fläche. Liegt die Fläche eine Platte höher (Duo), wird nichts geteilt, die Fliesen kommen auf den freien Teil. Abschaltbar mit `--set parts.tiles_split=false`.
- **Haltecheck (deine Ergänzung):** Jeder Schnitt muss von einem Teil darunter oder darüber überbrückt werden, das über die Schnittkante reicht. Sonst wandert der Schnitt eine Noppe in die Fläche; hilft auch das nicht, bleibt das Teil ganz. **Burghof:** 37 Hofteile reichen unter Mauern oder Türme; **17 davon wären nach dem Schnitt nur lose eingelegt gewesen.** Bei 12 hat das Verschieben um eine Noppe geholfen, 5 bleiben ganz. Der Hof kommt damit auf 90 % und wird gefliest.
- **Stabilität:** Jedes Modell mit einem Schnitt wird ganz neu geprüft (parallel zur Schrittplanung). Alle 14 Testmodelle sind ein stabiles Stück.
- **Teilezuwachs gegen den Richtwert +15 %:** Burg +10,1 % (1.657 → 1.825), Duo +5,5 % (1.025 → 1.081). Über 15 % liegen nur L-Winkel (+15,7 %) und zwei Körper (+15,8 %), unverändert seit 1.7.0, und das Herz (Voxeldatei, 12 → 25 Teile, +108 %; dort gilt jede Oberseite als flach). Der Lauf meldet das, nimmt aber nichts zurück.
- **Nebenbei:** Die Zeitreserve für die Stabilitätsprüfung war zu vorsichtig: In einem von zwei Läufen bekam die Burg deshalb gar keine Fliesen. Sie ist jetzt halb so groß (5 s + 0,01 s pro Teil); eine längere Prüfung geht vom Export-Puffer ab, der dafür reicht.
- **Bilder:** `out/tiles/vorher-nachher/teilen/` (links 85-%-Regel aus #45, rechts mit Teilen): `castle.png`, `Duo_Duolingo-32.png`, zur Kontrolle `two_bodies.png`. Zahlen pro Fläche in [benchmarks.md](benchmarks.md), „Cuts at the edge of flat faces“.

## Davor: #44, 85-%-Regel (in `main`, kein Release)

- **Regel:** Der Fliesen-Durchlauf plant jetzt erst alle Teile, ohne etwas zu ändern, und zählt dann für jede flache Fläche (zusammenhängende flache Zellen einer Lage): Welcher Anteil ihrer freien Oberseite liegt unter Teilen, die eine Fliese bekommen können? Ab 85 % wird die Fläche gefliest, darunter behält sie alle Noppen. Einstellbar mit `parts.tiles_min_share` (Standard 0,85; 0 = wie 1.7.0). Der Lauf sagt, wie viele Flächen ihre Noppen behalten.
- **Gemessen** (alle Testmodelle, Fliesen eingeschaltet, Tabelle in [benchmarks.md](benchmarks.md), „Tile share per face“): Würfel, Texturwürfel, L-Winkel, zwei Körper unverändert (gleiche Fliesen, 0,00 mm). Burg 99 → 0 Fliesen, Duo 22 → 0. Alle 14 ein stabiles Stück, Zeit wie 1.7.0 (ein Hasen-Lauf ohne jede Fliese brauchte einmal 146 s, zweimal danach 120 s: Streuung).
- **Warum Burg und Duo leer ausgehen:** Burghof 69 %, Bergfried-Dach 53 %, Mauerkronen 30 %, Turmdächer 0–8 %, Duos Sockel 51 % und 33 %. Der Grund ist immer derselbe: Teile, die über den Rand der flachen Fläche hinausreichen (die Burg wird eine Noppe zu breit voxelisiert, Duos Sockel hat einen gebogenen Rand). Passende Fliesen, Farben oder Zeit waren nie das Problem.
- **Bilder:** `out/tiles/vorher-nachher/85prozent/` (links Regel 1.7.0, rechts 85-%-Regel: `castle.png`, `Duo_Duolingo-32.png`, zur Kontrolle `two_bodies.png`).

## Davor: 1.7.0 (ROADMAP Punkt 9)

- Fazit 1.7.0: **Wo das 3D-Modell flach ist, legt mesh2brick auf Wunsch glatte Fliesen, und zwar genau auf die Höhe der Fläche:** Würfel, L-Winkel und die zwei Körper treffen ihr 3D-Modell damit exakt (Abweichung 0,00 mm statt im Mittel 0,66–0,83 mm), Kugel, Hase und Fliegenpilz behalten wie gewünscht ihre Noppen.
- **Alle Testmodelle bleiben ein stabiles Stück**, die Kästen brauchen 7–16 % mehr Teile; eingeschaltet wird es mit `tile` in `parts.categories`. Standardmäßig bleibt es aus, weil die Burg fleckig wirkt (deine Entscheidung 2026-11-11); das soll die 85-%-Regel in [#44](https://github.com/leckermatz79/mesh2brick/issues/44) beheben.

- **Zuerst die Messgröße für ganz 2.0** (eigener Commit): Wie weit liegt die Außenseite des Steinmodells vom 3D-Modell weg? Gemessen in echten LEGO-Millimetern, Noppen mitgerechnet (4,8 mm breit, 1,7 mm hoch), als Mittel und als „95 % der Oberfläche liegen höchstens so weit weg“, in mm und in Noppen. Grundlinie 1.6: Kästen 0,6–0,8 mm im Mittel (95 %: 4,05 mm, weil die Voxel eine Platte über der Oberseite enden und die Noppen dazukommen), runde Formen 1,8–2,4 mm (95 %: 4,2–4,9 mm, das sind die Voxeltreppen), Burg 3,3 / 8,0 mm. Der Release-Benchmark zeigt die Spalte jetzt immer; Tabelle in [benchmarks.md](benchmarks.md), „Shape fidelity baseline“. Die Messung dauert 0,5–7,5 s pro Modell (Duo 25–33 s).
- **legolizations eigener Fliesen-Tausch allein** (bisher mit `tile` eingeschaltet) bringt nichts: Er legt Fliesen auf die Treppen (Kugel 184, Fliegenpilz 117, Hase 61), keine einzige auf die Würfel-Oberseiten (dort liegen Steine, die tauscht er nicht) und kennt nur vier Fliesengrößen (Burghof fleckig). Die Abweichung ändert sich bei keinem Modell. Bilder: `out/tiles/vorher-nachher/legolization/`.
- **Die neue Regel:** Beim Voxelisieren schaut mesh2brick mit denselben senkrechten „Strahlen“ auf jede oberste Zelle: Liegt darüber eine waagerechte, ebene Fläche des 3D-Modells (höchstens 1° geneigt, höchstens 0,1 mm Höhenunterschied, mindestens 2 Zellen groß; Randzellen zählen dazu, wenn die Fläche sie mindestens zur Hälfte bedeckt)? Nur dort gibt es Fliesen. Eine Kuppel, auch ganz oben, ist nie flach.
- **Fliese auf die richtige Höhe:** Die Würfel sind 26,7 Steine hoch, die Voxel enden also eine Platte über dem Modell. Statt „2 Platten + Fliese“ wird ein Stein dort zu „1 Platte + Fliese“, die Oberseite liegt dann genau auf dem Modell (und es ist ein Teil weniger). Liegt die Fläche eine Platte höher (zwei Körper: 13,3 Steine), kommt eine Fliese auf den Stein. Platten werden zu gleich großen Fliesen (Teilezahl unverändert); alle neun Fliesengrößen aus legolizations Katalog werden genutzt, 2 × 3 und 2 × 8 als zwei Fliesen.
- **Stabilität:** Wo ein Teil schwerer wird (2 Platten + Fliese wiegen mehr als der Stein, eine aufgelegte Fliese wiegt etwas), prüft mesh2brick das ganze Modell neu, parallel zur Schrittplanung; hält es nicht mehr, werden die Fliesen zurückgenommen. Wird alles nur leichter, bleibt das Urteil von vorher stehen. Ist zu wenig Zeit, macht es nur die leichteren Umbauten und sagt, wie viele Oberseiten ihre Noppen behalten.
- **Darstellung:** Fliesen ohne Noppen in Vorschau, Schrittbildern und Teilekasten, in der Teileliste „Fliese 2 × 4“ mit BrickLink-/Rebrickable-Nummer (87079 usw.), als letzter Schritt aufgelegt. Die KI-Schicht weiß, was eine Fliese ist.
- **Einstellungen:** `parts.tiles: flat` (nur flache Flächen) oder `all` (auch Treppen), `parts.tiles_on_base: true/false` (unterste Lage). README (de/en) und Beispiel-Config erklären es.
- **Nebenbei behoben:** Mit eingeschalteter KI-Schicht, aber ohne API-Schlüssel ist `convert` bisher abgestürzt; jetzt wird die KI-Schicht übersprungen und der Lauf sagt „no API credentials: set ANTHROPIC_API_KEY“. Aufgefallen, weil in meiner Sitzung kein Schlüssel gesetzt war. Den Live-Test der Schritttexte mit Fliesen hast du gemacht (L-Winkel, 177 Teile, 39 von 39 Schritttexten, keine Probleme, 6,5 Cent); dazu prüft ein Test, dass Claude die Teile als „Fliese 2 × 4 (en: Tile …)“ und den Hinweis „Fliesen ohne Noppen, zuletzt auflegen“ bekommt.
- **Begründung mit Zahlen:** [ADR 0020](adr/0020-tiles-on-flat-tops.md) (die Nummer 0019 war schon vergeben). Ein Upstream-Vorschlag an legolization (Maske für `apply_tiles`, auch Steine, alle Fliesengrößen) steht als Kandidat #18 in [UPSTREAM.md](UPSTREAM.md); nichts in Punkt 9 wartet darauf, die Frage „Fork oder Warten“ stellt sich hier also nicht.

| Abnahme (Issue #42) | Ergebnis |
|---|---|
| Messgröße für alle Testmodelle in benchmarks.md, mit und ohne Fliesen; mit Fliesen nicht schlechter | **ja**: nirgends schlechter; Kästen 0,00 / 0,00 mm, Burg 3,31 → 3,25 mm, Duo 1,86 → 1,81 mm |
| Fliesen nur auf Flächen, die im 3D-Modell flach sind, nicht auf Kugel- und Hasen-Treppen; Bilder belegen es | **ja**: Würfel-, L-Winkel- und Zwei-Körper-Oberseite, Burghof und Mauern; Kugel, Hase, Fliegenpilz, Torus, Rakete: keine einzige. Die Hutmitte des Fliegenpilzes ist gewölbt, bekommt also keine. **Teilweise:** Burgtürme und Duos Sockel behalten am Rand Noppen (siehe Einschränkungen) |
| Alle Testmodelle ein stabiles Stück | **ja**, 14 von 14 |
| Zeit höchstens +20 % gegenüber 1.6 | **13 von 14**: −4 % bis +9 %; **L-Winkel +20,4 %** (30 → 36 s, 24 Teile mehr in legolizations Schrittsuche) |
| PDF des Texturwürfels unter 10 MB | **ja**: 9,83 MB (1.6: 9,56 MB) |
| Teilezahl: Platte → Fliese unverändert, Stein-Umbau pro Modell ausgewiesen | **ja** (Tabelle unten) |
| Ohne `tile` alles wie 1.6 (Regressionstest) | **ja**, Test vorhanden; legolizations eigener Tausch wird nie mehr benutzt |
| Studio-Prüfung durch dich | **offen** – Befehl unter „Offene Kleinigkeiten“ |
| Tests: Maske (Ebene, Treppe, Kuppel), Steinumbau mit Stabilitätsprüfung, Darstellung ohne Noppen, Export-Nummern | **ja**: 850 Tests grün |
| Zusätzlich: Stabilität nie schlechter, Zeitgrenze, Farben, LDraw-Prüfung, Teileschätzung | **ja**: Rücknahme getestet; nur Fliesen in Farben, die es gibt; LDraw-Datei liest sich streng wieder ein; `inspect` trifft weiter 14 von 14 |

## Messwerte mit Fliesen (alle Testmodelle, Endstand)

| Modell | Fliesen | Teile 1.6 → mit Fliesen | Abweichung Mittel / 95 % in mm (1.6 → mit) | Zeit 1.6 → mit |
|---|---:|---|---|---|
| Würfel (STEP und STL) | 139 | 1.952 → 2.091 (+7 %) | 0,83 / 4,05 → **0,00 / 0,00** | 250 → 248 s |
| Texturwürfel | 186 | 2.280 → 2.466 (+8 %) | 0,83 / 4,05 → **0,00 / 0,00** | 245 → 242 s |
| L-Winkel | 24 | 153 → 177 (+16 %) | 0,60 / 4,05 → **0,00 / 0,00** | 30 → 36 s |
| Zwei Körper | 96 | 606 → 702 (+16 %) | 0,66 / 3,20 → **0,00 / 0,00** | 163 → 177 s |
| Burg | 99 | 1.657 → 1.676 (+1 %) | 3,31 / 8,00 → 3,25 / 8,00 | 251 → 250 s |
| Duo (32, nur lokal) | 22 | 1.025 → 1.047 (+2 %) | 1,86 / 4,23 → 1,81 / 4,23 | 128 → 134 s |
| Herz (Voxeldatei) | 2 | 12 → 16 | 0,08 / 0,85 → 0,06 / 0,00 | 4 → 4 s |
| Kugel, Vertex-Kugel, Hase, Fliegenpilz, Torus, Rakete | 0 | unverändert | unverändert (1,5–2,4 / 3,2–4,9) | ±4 % |

Bilder für jedes Modell (links 1.6, rechts mit Fliesen): `out/tiles/vorher-nachher/fliesen/`.

## Als Nächstes

1. **Deine Abnahme von [#46](https://github.com/leckermatz79/mesh2brick/issues/46)** an den Bildern (Frage unten); danach Fliesen standardmäßig an und Release 2.0.0 (mit Teilen oder, wenn es dich nicht überzeugt, Variante A ohne Teilen), Galerie neu. Zur Erinnerung, was #46 ist (deine Wahl B vom 2026-11-11): Teile, die über den Rand einer flachen Fläche reichen, werden an der Flächengrenze geteilt (innen Platte + Fliese, außen bleibt der Stein), bevor die 85-%-Regel greift. Zuerst messen: geteilte Teile und Teilezuwachs je Fläche für Burg und Duo. Höchstens +15 % Teile pro Modell, darüber behält die Fläche Noppen. Stabilität nach dem Teilen neu prüfen, besonders unter Mauern. Die vier Kästen bleiben unverändert. Abnahme: du an Vergleichsbildern von Burg und Duo; überzeugt es, gehen Fliesen mit Teilen an und es wird 2.0.0, sonst Variante A (Fliesen an nur mit 85-%-Regel, ebenfalls 2.0.0).
2. **ROADMAP 8 – mehr Dachsteine** (Reihenfolge in 2.0: 9, dann #44, dann 8, 10, 11, 12, 13). Die Messgröße von heute ist die Grundlinie dafür: Bei runden Formen machen die Voxeltreppen 1,8–2,4 mm Abweichung aus, Noppen nur 0,04–0,3 mm; Dachsteine an den Treppenkanten sind dort der Hebel. Hängt Punkt 8 an einer Änderung in legolization, steht die Frage „Fork oder Warten“ an (deine Entscheidung, vereinbart am 2026-11-07). Danach runde Teile, SNOT, Farbverfügbarkeit bei der Platzierung und `choose_part` (Roadmap 10–13). Upstream: Antworten auf legolization #88/#89, #90/#91 und #99 sowie trimesh #2669 abwarten.

Alle früheren Punkte (1.x, Roadmap 1–8 der ersten Liste) sind fertig; Einzelheiten in [CHANGELOG.md](../CHANGELOG.md) und in den [Issues mit Label `roadmap`](https://github.com/leckermatz79/mesh2brick/issues?q=label%3Aroadmap).

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
| Fliesen liegen nur auf Teilen, deren ganze Oberseite unter der flachen Fläche liegt. Wo Teile über den Rand der Fläche reichen, bleiben Noppen: bei der Burg die Turmränder (ihr offenes STEP-Netz wird eine Noppe zu breit voxelisiert), bei Duo der gebogene Sockelrand; dort stehen die aufgelegten Fliesen eine Platte über den Randteilen. Deshalb sind Fliesen standardmäßig aus. | seit #44 behalten solche Flächen ganz ihre Noppen (statt fleckig); Randteile aufteilen: [#46](https://github.com/leckermatz79/mesh2brick/issues/46) |
| Fliesen nur auf waagerechten Flächen. Schräge, aber ebene Flächen (ein Dach) behalten Noppen. | ROADMAP 8 (Dachsteine) |
| Kleine Modelle mit vielen umgebauten Steinen brauchen etwas länger, weil legolizations Schrittsuche mehr Teile sieht (L-Winkel 30 → 36 s). | akzeptieren |
| Liegt eine flache Fläche mehr als eine Platte von der Voxel-Oberkante entfernt, kommt die Fliese nur eine Platte näher (nur bei der Burg, 32 von 375 Fliesenfeldern). Platten werden nie tiefer gelegt. | akzeptieren |
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
| 2026-11-11 | Fliesen standardmäßig an (ROADMAP 9)? | **Vorerst aus, Release 1.7.0 wie im PR.** Grund: An der Burg wirkt das Ergebnis fleckig (Turmränder und Teilflächen behalten Noppen). Einschalten mit `tile` in `parts.categories`. |
| 2026-11-11 | Fliesen auch auf Treppen runder Formen? | **Nein.** `parts.tiles: flat` bleibt Standard (`all` nur auf Wunsch). |
| 2026-11-11 | Unterste Lage (Sockel) ohne Fliesen? | **Nein, der Sockel bekommt Fliesen** (`parts.tiles_on_base: true` bleibt Standard). |
| 2026-11-11 | Was kommt vor ROADMAP 8? | **Ein eigenes Issue ([#44](https://github.com/leckermatz79/mesh2brick/issues/44)):** Eine flache Fläche wird nur gefliest, wenn mindestens 85 % ihrer freiliegenden Oberseite fliesbar sind, sonst behält die ganze Fläche Noppen. Abnahme an Burg und Duo per Vergleichsbild durch dich. Überzeugt es, gehen Fliesen standardmäßig an und es wird 2.0.0. |
| 2026-11-11 | KI-Live-Test mit Fliesen (offen aus ROADMAP 9) | **Von dir gemacht:** L-Winkel mit Fliesen, 177 Teile, 39 von 39 Schritttexten, keine Probleme, 6,5 Cent. |
| 2026-11-11 | Überzeugt die 85-%-Regel (#44)? | **B: erst Randteile aufteilen.** Bilder gesehen: Die zwei Körper überzeugen, Burg und Duo haben mit der 85-%-Regel keine Fliesen mehr. Fliesen bleiben vorerst aus. #44 ist geschlossen, weiter in [#46](https://github.com/leckermatz79/mesh2brick/issues/46). |
| 2026-11-11 | Wie sollen Randteile geteilt werden (#46)? | **An der Flächengrenze, bevor die 85-%-Regel greift:** innen Platte + Fliese, außen bleibt der Stein. Erst messen (geteilte Teile und Teilezuwachs je Fläche für Burg und Duo). Höchstens +15 % Teile pro Modell, darüber behält die Fläche Noppen. Stabilität nach dem Teilen neu prüfen, besonders unter Mauern. Die vier Kästen bleiben unverändert. Abnahme durch dich an Vergleichsbildern von Burg und Duo: überzeugt es, Fliesen standardmäßig an und 2.0.0; sonst Variante A (Fliesen an nur mit der 85-%-Regel, 2.0.0). |

## Fragen an dich

1. **Überzeugt dich das Teilen am Flächenrand (#46)?** Bilder: `out/tiles/vorher-nachher/teilen/` (links 85-%-Regel, rechts mit Teilen; `castle.png`, `Duo_Duolingo-32.png`). Bei **Ja** schalte ich Fliesen mit Teilen standardmäßig ein, erneuere die Galerie und bereite Release 2.0.0 vor. Bei **Nein** wird es Variante A: Fliesen an nur mit der 85-%-Regel (Kästen glatt, Burg und Duo mit Noppen), ebenfalls 2.0.0. **Standard, wenn keine Antwort kommt:** Fliesen bleiben aus, es geht mit ROADMAP 8 weiter.

## Offene Kleinigkeiten

- **Studio-Prüfung mit Fliesen (Abnahme #42, von dir):** Duo mit Fliesen bauen und in BrickLink Studio öffnen (Datei → Öffnen, nicht Import):
  `uv run mesh2brick convert samples/Duo_Duolingo.3mf -o out/studio-fliesen --set "parts.categories=[brick, plate, slope, tile]"`
  Dann `out/studio-fliesen/Duo_Duolingo.mpd` öffnen. Prüfen: keine Überlappungen, keine schwebenden Fliesen (bei Duo liegen die 22 Fliesen auf dem Sockel). Wer mehr Fliesen sehen will: dasselbe mit `tests/fixtures/two_bodies.step` (96 Fliesen auf Steinen) oder `tests/fixtures/cube_10mm.stl`.
- **Upstream-Kandidat #18** (Maske für legolizations `apply_tiles`, auch Steine, alle Fliesengrößen): Text steht in [UPSTREAM.md](UPSTREAM.md); einreichen nur nach deinem OK, eilt nicht.
- **Rakete im Vergleich** (Wiedervorlage bei 2.x Punkt 17): legolizations Suche (Standard, mit blauen Baugruppen) gegen die geprüfte Schichtfolge mit Mini-Vorbauten:
  `uv run mesh2brick convert tests/fixtures/rocket.blend -o out/rocket-suche`
  `uv run mesh2brick convert tests/fixtures/rocket.blend -o out/rocket-schichten --set steps.sequencing=checked-layers`
  Danach `out/rocket-suche/rocket.pdf` und `out/rocket-schichten/rocket.pdf` nebeneinanderlegen (gemessen: 11 gegen 0 Schritte mit „Halte fest“).
