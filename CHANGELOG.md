# Changelog

Alle nennenswerten Änderungen am Job-Agenten, nach Versionen gegliedert und
angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/). Die
Versionen folgen [SemVer](https://semver.org/lang/de/) (0.x): Eine neue Quelle
oder Funktion hebt die Minor-Version, reine Fehlerbehebungen heben die
Patch-Version. Nummern wie (#12) verweisen auf die Issues im Repo.

## Unveröffentlicht

### Neu

### Geändert

### Behoben
- Ein gemerkter vollständiger Lauf mit einem Datum in der Zukunft (etwa nach einer
  verstellten Uhr) bestimmt den Suchzeitraum nicht mehr; es zählen nur Läufe bis
  heute (#48)

## 0.7.0 – 2026-11-20

### Neu
- `CHANGELOG.md` beschreibt die Versionen ab 0.2.0; jedes Ticket trägt seine
  Änderung hier unter „Unveröffentlicht“ ein (#35)
- Typprüfung mit pyright im Modus „standard“ über `src/` und `tests/`, lokal per
  `uv run pyright` und als eigener Schritt in der CI (#36)
- Suchzeitraum ab dem letzten vollständigen Lauf: Bundesagentur und Arbeitnow
  holen die Tage seither plus 1, sodass ausgefallene Tage, Quellenfehler und
  unbewertete Anzeigen nichts verlieren; der Report nennt ihn über dem
  Quellenstatus, `veroeffentlichtseit` ist Start- und Höchstwert, in der
  mitgelieferten `config.toml` 7 Tage (#37)
- Sperre gegen gleichzeitige Läufe: Ein zweiter Lauf bricht mit Meldung und
  Exit-Code 1 ab, bevor er sucht oder bewertet. Die Sperre gibt das
  Betriebssystem frei, auch nach Absturz; Rückmeldung, Profil-Vorschlag und
  Demo-Lauf sperren nicht (#38)
- Abschnitt „Aufbau“ im README: Ein Mermaid-Diagramm zeigt den Lauf mit den
  Seams Quelle, Sprachmodell und `Store`, ihren Adaptern, den Fakes der Tests,
  den Demo-Teilen und dem Zusammenbau in der Kommandozeile (#44)

### Geändert
- `config.toml` wird streng geprüft: Unbekannte Abschnitte und Schlüssel brechen
  das Laden mit „meintest du …?“ und dem ähnlichsten Namen ab, falsche
  Werttypen mit dem erwarteten Typ; alle Fehler erscheinen in einer Meldung (#40)
- `config.toml` prüft auch Wertebereiche: `mindest_score` auf der Score-Skala,
  `nachfassen_ab_tag` und `nachfassen_bis_tag` ab 0 und in dieser Reihenfolge,
  `umkreis` ab 0 und `ats` nur `greenhouse` oder `lever`, bei Tippfehlern mit
  dem ähnlichen Namen
- Das Anthropic-SDK muss mindestens Version 2.5 haben; ältere Versionen kennen
  die Fehlerklassen nicht, nach denen der Report die Ursache unbewerteter
  Anzeigen nennt
- `output/abgebrochen.log` wächst nur noch auf etwa 1 MB; danach bleibt genau
  eine ältere Kopie `abgebrochen.log.1`. Das README weist darauf hin, dass
  `ANTHROPIC_LOG=debug` Anzeigen-Volltexte auf die Konsole bringt, nicht ins Log (#43)
- Die Score-Skala 1 bis 5 ist an einer Stelle festgelegt; Bewertung,
  Rückmeldung und Report richten sich danach, und der Bewerbungsstatus kommt
  typisiert aus dem Store in den Report (#41)
- Scheitern alle Bewertungen eines Laufs auf dieselbe Art, nennt der Report
  bei den unbewerteten Anzeigen die Ursache: „API-Key fehlt“, „Sprachmodell
  nicht erreichbar“ (auch bei Zeitüberschreitung) oder „Antworten unbrauchbar“;
  bei sonstigen Fehlern wie einem ungültigen Key oder einem erreichten
  Ausgabenlimit bleibt es bei der Zahl (#39)

### Behoben
- Profil-Vorschlag: Schlägt das Sprachmodell dieselbe Änderung mehrfach vor, gilt
  sie nur einmal und die Wiederholung wird als nicht angewandt angezeigt. Auszüge
  werden im Suchprofil vor dem Profil-Vorschlag gesucht; eine Änderung, deren
  Auszug sich mit einer anderen überschneidet, wird ebenfalls nicht angewandt (#42)
- Die Rückmeldung lehnt `--am` beim eigenen Score und eine riesige Zahl als
  Score mit deutscher Meldung und Exit-Code 1 ab, statt `--am` still zu
  ignorieren oder mit einem Traceback abzubrechen (#41)
- Die Bundesagentur blättert je Suchbegriff durch alle Ergebnisseiten statt nur
  die erste zu holen, höchstens 5 Seiten. Erreicht sie oder Arbeitnow (10 Seiten)
  die Grenze, steht „Ergebnisse abgeschnitten“ im Quellenstatus, und der Lauf
  zählt nicht als vollständig, statt Anzeigen still zu verlieren. Das Blättern
  richtet sich auch nach der Gesamtzahl `maxErgebnisse` der API und zählt
  wiederholte Anzeigen nur einmal
- Der Suchzeitraum wächst nie über 100 Tage, mehr nimmt die Bundesagentur nicht
  an; ohne `veroeffentlichtseit` sind es auch beim ersten Lauf 100 statt
  unbegrenzt, und `veroeffentlichtseit` muss zwischen 1 und 100 liegen. Ein gemerkter
  vollständiger Lauf in der Zukunft (verstellte Uhr) zählt nicht, dann gilt der
  Startwert, und der Report nennt den Lauf statt „erster Lauf“
- Der Suchzeitraum im Report nennt das Datum des letzten vollständigen Laufs mit
  Jahr, wenn es nicht im Jahr des Reports liegt, damit es über den Jahreswechsel
  eindeutig bleibt
- Profil-Vorschlag: Eine Änderung, die nicht angewandt wird, erscheint auch bei
  mehrfachem Vorschlag nur einmal; eine Änderung ohne Wirkung (alter gleich
  neuer Text) gilt als nicht angewandt und blockiert keine andere an derselben
  Stelle; ein leerer oder im Suchprofil fehlender Auszug heißt „Auszug fehlt“
  statt „nicht eindeutig“
- Die Meldung „Es läuft schon ein anderer Lauf“ nennt die Sperrdatei, weil unter
  Windows auch eine kaputte Sperrdatei so erscheinen kann; fehlt der Ordner der
  Datenbank, nennt die Meldung die Datenbank statt der Sperrdatei

## 0.6.0 – 2026-11-15

### Neu
- Unbewertete Anzeigen: Scheitert eine Bewertung, zählt der Report die Anzeige
  als unbewertet, und der nächste Lauf versucht es erneut (#29)
- Log-Datei pro Lauf neben dem Report (`output/YYYY-MM-DD.log`), ohne
  Anzeigen-Volltexte; ein abgebrochener Lauf schreibt `output/abgebrochen.log`
  (#32)
- Demo-Sprachmodell, über das der Demo-Lauf denselben Weg der Bewertung nimmt
  wie ein echter Lauf (#25)

### Geändert
- Bewertung und Profil-Vorschlag sprechen nur noch mit dem Seam
  `LanguageModel`; Haiku und Sonnet werden beim Zusammenbau gewählt (#23, #24)
- Speicherung als Klasse `Store` mit fachlichen Fragen statt freier
  SQL-Funktionen; Report und Merken gelingen zusammen oder gar nicht (#26, #27)
- Der Lauf ist `run()` und bekommt alles übergeben; Lauf, Rückmeldung und
  Profil-Vorschlag bauen sich in der Kommandozeile zusammen (#28, #30)
- Alle drei Kommandos brechen mit klarer Meldung und Exit-Code 1 ab statt mit
  einem Traceback (#31)
- `config.toml` ist in die Abschnitte `[suche]`, `[bundesagentur]`,
  `[watchlist]` und `[report]` geteilt; das alte flache Format wird nicht mehr
  gelesen, die Meldung nennt den neuen Platz jedes alten Schlüssels (#33)
- Wegweiser in `CLAUDE.md` und die ADRs auf den Stand nach dem Umbau gebracht
  (#34)

### Behoben
- Ein Report, der beim Schreiben scheitert, bleibt nicht halb liegen, und
  gleichzeitige Läufe überschreiben sich nicht gegenseitig (#31)
- Store-Transaktionen und Lesefehler hinterlassen keine Teilzustände mehr (#31)
- `config.toml` und `profile.md` werden auch mit BOM gelesen, Kodierungsfehler
  klar gemeldet (#31)
- Ein bekannter Schlüssel im falschen Abschnitt der Konfiguration fällt nicht
  mehr still auf den Standardwert zurück (#33)
- Die Rückmeldung prüft die Score-Skala auch ohne Kommandozeile; ein
  unbrauchbares Feld `modellfehler` verwirft nicht mehr den ganzen
  Profil-Vorschlag (#30)
- Die Log-Datei ist auch bei Absturz und mit `python -m` vollständig (#32)
- `profile.md` wird in einem Schritt ersetzt und bleibt bei vollem Datenträger,
  Verknüpfung, Schreibschutz oder Abbruch heil
- Einzelne Surrogate (halbe Emojis) in Anzeigen und Modellantworten brechen
  Merken, Report und Profil-Vorschlag nicht mehr ab
- Eine Bewerbung wird bei jeder Anzeige auch über deren Quell-ID erkannt, nicht
  nur über Firma und Titel, also auch bei einer Anzeige ohne Firma. Die
  Textabweichung vergleicht nicht mehr mit dem gerade gemerkten Text: Wo der
  Text zum Zeitpunkt der Bewerbung fehlt, steht „Text nicht vergleichbar“ statt
  eines falschen „Text identisch“

## 0.5.1 – 2026-11-12

### Neu
- Ein Test erkennt deutsche Bezeichner im Code automatisch (#17)
- Vertragstest: Keine Quelle wirft bei kaputten Antworten (#18)
- Der Demo-Report ist als Golden-File gegen ungewollte Änderungen gesichert
  (#19)
- Ablauf für Sitzungen in eigenen Worktrees unter `docs/agents/` (#20, #22)

### Geändert
- Die Details der Quellen stehen in `docs/quellen.md` statt in `CLAUDE.md`
- Zeilenenden im Repo per `.gitattributes` auf LF festgelegt

### Behoben
- Quellen prüfen die Feldtypen jeder Anzeige: Ein Pflichtfeld mit falschem Typ
  kostet nur diesen Eintrag, statt als falscher Wert in Bewertung und Report zu
  landen
- Ein optionales Feld mit falschem Typ wird zu `None`, statt die ganze Antwort
  ungültig zu machen
- Der Vertragstest sichert optionale Felder für alle Quellen ab, auch in
  Unterobjekten wie dem Ort der Bundesagentur; bei Arbeitnow lässt ein
  Veröffentlichungsdatum als Wahrheitswert, NaN oder Infinity eine Anzeige
  nicht mehr als zu alt verschwinden (#21)

## 0.5.0 – 2026-11-12

### Neu
- ADR 0005: englische Bezeichner im Code, deutsche Fachsprache für alles, was
  Menschen lesen (#7)

### Geändert
- Bezeichner im ganzen Code englisch nach der Spalte „Im Code“ im Glossar; das
  DB-Schema bleibt deutsch (#8, #9, #10, #11)
- Das Kommando für den Profil-Vorschlag heißt jetzt
  `python -m jobagent.profile_suggestion` (#11)
- Quellen sind Adapter am Seam `Source`, zuerst die Bundesagentur (#12)
- Arbeitnow blättert pro Lauf einmal über höchstens 10 Seiten und filtert die
  Suchbegriffe lokal, statt für jeden Suchbegriff erneut zu blättern
  (#13)
- Die Firmen-Watchlist ist ein eigener Adapter mit Greenhouse- und Lever-Board
  (#14)
- Alter Quellen-Code entfernt, der Quellenstatus entsteht beim Lauf (#15)

### Behoben
- Verformte Felder einer API-Antwort melden die Quelle als ungültige Antwort,
  statt den Lauf ins Sicherheitsnetz zu werfen; das Sicherheitsnetz nennt die
  Suchbegriffe im Fehler (#12, #14)

## 0.4.0 – 2026-11-11

### Neu
- CI mit Lint, Formatprüfung und Tests (#1)
- Vier ADRs zu den bewussten Entscheidungen: Datensparsamkeit, nur erlaubte
  Quellen, der Mensch entscheidet, Modellwahl Haiku/Sonnet (#3)
- Demo-Lauf `python -m jobagent.main --demo` ohne API-Key, Konfiguration und
  Netz (#4)

### Geändert
- Quellen, Bewertung und Konfiguration sind im Lauf austauschbar (#2)
- README als Schaufenster mit Demo-Lauf und Entscheidungen, dazu die
  Repo-Beschreibung (#5, #6)

## 0.3.0 – 2026-11-08

### Neu
- Treffer sind je Report durchnummeriert; gespeichert werden dazu die
  Bewertung und ein Hash der Beschreibung
- Quellenstatus im Report: je Quelle die Zahl der Anzeigen und ob sie
  ausgefallen ist
- Rückmeldung per `python -m jobagent.feedback`: Bewerbungen mit Status und
  eigene Scores zu einem Treffer erfassen
- Block „Bereits beworben“ für Stellen, auf die schon eine Bewerbung läuft,
  mit Hinweis auf Textabweichungen
- Nachfass-Hinweis für unbeantwortete Bewerbungen
- Profil-Vorschlag: Sonnet leitet aus dem Feedback Änderungen am Suchprofil
  ab, die erst nach Bestätigung übernommen werden
- Glossar der Fachbegriffe

### Geändert
- Treffer unter dem Mindest-Score erscheinen nur einzeilig am Ende des Reports

### Behoben
- Ein weiterer Lauf am selben Tag überschreibt den vorhandenen Report nicht
  mehr, sondern schreibt `YYYY-MM-DD-2.md` usw.

## 0.2.0 – 2026-11-07

Erste Version mit Tag.

### Neu
- Drei Quellen: Bundesagentur für Arbeit, Arbeitnow und eine
  Firmen-Watchlist über Greenhouse und Lever
- Dedupe über SQLite: Schon gesehene Anzeigen kommen nicht wieder
- Bewertung jeder neuen Anzeige durch Claude Haiku gegen `profile.md`, als
  strikt strukturierte Antwort
- Markdown-Report `output/YYYY-MM-DD.md`, sortiert nach Score
- README

### Geändert
- `kurzfazit` auf einen kurzen Satz begrenzt

### Behoben
- Die Bundesagentur-Quelle liest das echte Schema der Jobsuche-API statt des
  abweichend dokumentierten
- Liefert das Modell `passt`, `passt_nicht` oder `luecken` als Text statt als
  Liste, geht der Treffer nicht mehr verloren
