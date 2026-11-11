[![CI](https://github.com/bettinawoste-wq/jobagent/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bettinawoste-wq/jobagent/actions/workflows/ci.yml)

*A personal agent that searches German job boards and selected company job
boards for new postings, has Claude rate each one against a personal search
profile and writes a ranked Markdown report. It never applies or sends
anything on its own: it only makes suggestions, and every decision stays with
the human. Try it in one command with `--demo`, no API key or network needed.*

# Job-Agent

Persönlicher Agent, der täglich (bzw. an festgelegten Tagen) neue, passende
Stellenanzeigen sucht, sie gegen ein individuelles Suchprofil bewertet und
eine Markdown-Datei mit den besten Treffern schreibt.

**Wichtig:** Der Agent schickt nie Bewerbungen oder Nachrichten ab — er
liefert ausschließlich Vorschläge zum manuellen Durchsehen.

## Ausprobieren

```bash
uv sync
uv run python -m jobagent.main --demo
```

Der Demo-Lauf zeigt einen vollständigen Report mit erfundenen Anzeigen und
vorgefertigten Bewertungen. Er braucht keinen API-Key, holt nichts aus dem Netz
und liest oder speichert nichts Persönliches; der Report erscheint nur in der
Konsole (mit `--ausgabe ORDNER` zusätzlich als Datei).

Auszug aus der Ausgabe (gekürzt, `…` markiert Auslassungen):

```markdown
# Stellenvorschläge 2026-11-11

## Quellen
- Bundesagentur für Arbeit (Demo): 3 Anzeigen
- Arbeitnow (Demo): 3 Anzeigen
- Firmen-Watchlist (Demo): FEHLER, 2 Anzeigen (Musterwerk AG: Board nicht erreichbar)

## Nachfassen
- Data Engineer (m/w/d) (Datenwerk Muster GmbH): seit 18 Tagen keine Antwort, nachhaken? (beworben am 24.10.2026)

## 1. Full-Stack-Entwickler (m/w/d) Python/TypeScript – Score 5/5
- Firma: Fiktiva Software GmbH
- Ort: Beispielstadt
- Link: https://example.com/stellen/demo-ba-1
- Kurzfazit: Sehr guter Match für die erste Wunschrolle.
- Passt: Python und JavaScript/TypeScript, Full-Stack wie gesucht, Hybrid in Beispielstadt

## 2. Data Scientist (m/w/d) – Score 4/5
- Firma: Lorem Data GmbH
- Ort: Remote
- Link: https://example.com/stellen/demo-an-2
- Kurzfazit: Gute Passung zur vierten Wunschrolle.
- Passt: Data Science mit Python, Remote
- Lücken: scikit-learn nur in Grundzügen

…

## Weitere Treffer (Score unter 3)
- **6.** Werkstudent Data Analytics (m/w/d) (Testfeld Robotics GmbH, Beispielstadt) – Score 2/5: Inhaltlich nah, aber falsches Level. – https://example.com/stellen/demo-wl-2
…

## Bereits beworben
- **8.** Python Developer (w/m/d) (Beispiel Tech, Remote) – Score 4/5 – gespräch, beworben am 07.10.2026 – Text weicht von deiner Bewerbung ab – https://example.com/stellen/demo-an-1
```

Die Watchlist-Quelle fällt im Demo-Lauf absichtlich teilweise aus: So sieht
man, dass eine gescheiterte Quelle den Lauf nicht abbricht, sondern im
Quellenstatus ausgewiesen wird.

## Entscheidungen

Die wichtigsten Grundsatzentscheidungen sind als ADRs in
[`docs/adr/`](docs/adr/) festgehalten:

- [Keine Volltexte von Anzeigen speichern](docs/adr/0001-datensparsamkeit.md):
  Gespeichert werden nur Metadaten, die Bewertung und ein Hash der
  Beschreibung, über den Textabweichungen erkannt werden.
- [Nur Quellen mit öffentlicher Schnittstelle nutzen](docs/adr/0002-nur-erlaubte-quellen.md):
  Bundesagentur, Arbeitnow und Greenhouse/Lever ja, Scraper für LinkedIn,
  Xing oder Indeed nein.
- [Der Mensch entscheidet, der Agent schlägt nur vor](docs/adr/0003-der-mensch-entscheidet.md):
  keine automatischen Bewerbungen, Bewerbungsstatus und Suchprofil ändern sich
  nur durch eigene Angabe bzw. Bestätigung.
- [Haiku für die Bewertung, Sonnet für den Profil-Vorschlag](docs/adr/0004-modellwahl-haiku-sonnet.md):
  das günstige, schnelle Modell für viele kleine Bewertungen, das stärkere für
  den seltenen, anspruchsvollen Profil-Vorschlag.
- [Englische Bezeichner, deutsche Fachsprache](docs/adr/0005-englische-bezeichner-deutsche-fachsprache.md):
  Namen im Code sind englisch nach dem Glossar, alles, was Menschen lesen,
  bleibt deutsch.

## Ablauf

```
Bundesagentur-API   Arbeitnow-API   Firmen-Watchlist
(Suche + Details)   (kein Key)      (Greenhouse/Lever pro Firma)
        │                 │                 │
        └────────┬────────┴─────────┬───────┘
                  ▼
    fetch.py  ──►  store.py (SQLite-Dedupe: schon gesehene IDs raus)
        │
        ▼
    score.py  ──►  Claude Haiku bewertet jede neue Anzeige
        │          gegen profile.md (strukturierte JSON-Antwort:
        │          score, passt, passt_nicht, luecken, kurzfazit)
        ▼
    report.py ──►  output/YYYY-MM-DD.md (sortiert nach Score)
```

Jeder Schritt ist defensiv: Schlägt eine einzelne Anzeige fehl (API-Fehler,
ungültige LLM-Antwort), wird das geloggt und die Anzeige beim nächsten Lauf
erneut versucht — der Gesamtlauf bricht nie ab.

## Stack

- Python 3.12, Abhängigkeitsverwaltung per [`uv`](https://docs.astral.sh/uv/)
- `httpx` für HTTP-Zugriffe, `sqlite3` (Standardbibliothek) für Dedupe
- [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) mit
  Claude Haiku für die Bewertung (strukturierte Antwort per Tool-Use)
- `pytest` (alles gemockt/mit Fixtures, kein Live-Zugriff in Tests) und
  `ruff` für Lint/Format

## Setup

```bash
uv sync
```

Suchprofil anlegen (wird nicht committed, siehe `.gitignore`):

```bash
cp profile.example.md profile.md
# profile.md mit eigenen Angaben fuellen
```

API-Key setzen (niemals im Code/Repo):

```powershell
[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "dein-key", "User")
```

Suchparameter in `config.toml` anpassen (Ort, Umkreis, Zeitfenster,
Suchbegriffe, optional `[[firmen]]` für eine Watchlist konkreter
Greenhouse-/Lever-Jobboards).

## Verwenden

```bash
uv run python -m jobagent.main
```

Ergebnis landet in `output/YYYY-MM-DD.md`, weitere Läufe am selben Tag in
`output/YYYY-MM-DD-2.md` usw. Ein vorhandener Report wird nie überschrieben.
Die Treffer sind je Report ab 1 durchnummeriert. Oben im Report steht je
Quelle, wie viele Anzeigen sie geliefert hat und ob sie ausgefallen ist.
Treffer unter `mindest_score` (`config.toml`, Standard 3) erscheinen nur
einzeilig am Ende.
Ohne neue Treffer wird eine kurze Notiz statt einer leeren Datei geschrieben.

## Rückmeldung geben

Treffer werden über Report und Nummer angesprochen:

```bash
uv run python -m jobagent.feedback 2026-11-06 3 beworben
uv run python -m jobagent.feedback 2026-11-06 3 beworben --am 2026-11-01
uv run python -m jobagent.feedback 2026-11-06 3 gespräch
uv run python -m jobagent.feedback 2026-11-06 2 score 4 "Dienstleister ist okay"
```

Status sind `beworben`, `gespräch`, `absage`, `zusage` und `zurückgezogen`;
`zurücknehmen` löscht eine versehentlich erfasste Bewerbung. Der Status ändert
sich nur durch solche Angaben, nie von selbst.

Bewerbungen ohne Treffer (z. B. direkt auf einer Karriereseite) gehen so:

```bash
uv run python -m jobagent.feedback beworben --firma "Firma X" --titel "Data Engineer"
```

Steht eine Bewerbung auf `beworben` und liegt 14 bis 28 Tage zurück
(`nachfassen_ab_tag`, `nachfassen_bis_tag` in `config.toml`), erinnert der
Report ans Nachhaken. Danach verschwindet der Hinweis, der Status bleibt.

Erscheint eine Stelle erneut, auf die du dich beworben hast, steht sie im
Report im Block „Bereits beworben“, mit Status, Datum und dem Hinweis, ob der
Text von dem bei deiner Bewerbung abweicht. Dieselbe Stelle heißt: gleiche Firma
und gleicher Titel, unabhängig von Schreibweise, (m/w/d) und Rechtsform.

## Suchprofil aus Feedback verbessern

```bash
uv run python -m jobagent.profile_suggestion
```

Claude Sonnet wertet das noch offene Feedback aus und unterscheidet dabei
Lücken im Profil von Lesefehlern der Bewertung. Du siehst die Änderungen als
Diff und entscheidest: übernehmen, ablehnen oder abbrechen. Vor dem Übernehmen
wird eine Sicherung `profile.sicherung-….md` angelegt. Ab 5 offenen
Rückmeldungen erinnert der Report daran.

## Tests

```bash
uv run pytest
uv run ruff check . && uv run ruff format .
```

## Automatisierung

Lässt sich z. B. per Windows Task Scheduler (`Register-ScheduledTask`) oder
cron an bestimmten Wochentagen morgens automatisch starten.

## Hinweis zur Entstehung

Dieses Projekt ist iterativ mit [Claude Code](https://claude.com/claude-code)
entstanden (KI-Pair-Programming): Architektur und Vorgaben kamen aus
`CLAUDE.md`, jeder Schritt wurde einzeln geplant, implementiert, getestet und
committed. Dabei wurden auch reale Bugs gefunden und gefixt, zum Beispiel ein
Abweichen der Live-API vom dokumentierten Schema und ein nicht abgefangener
Fehlertyp bei fehlendem API-Key — beide erst durch echte End-to-End-Läufe
aufgefallen, nicht durch die Unit-Tests allein.
