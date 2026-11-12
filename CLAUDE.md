# Job-Agent

Persönlicher Agent, der täglich neue, passende Stellenanzeigen sucht, gegen mein Profil bewertet und eine Markdown-Datei mit den besten Treffern schreibt. Er schickt nie Bewerbungen oder Nachrichten ab, er liefert nur Vorschläge.

## Stack
- Python 3.12, Abhängigkeiten per `uv`
- `httpx` für HTTP, `sqlite3` aus der Standardbibliothek
- `anthropic` SDK für die Bewertung (Haiku) und den seltenen Profil-Vorschlag (Sonnet), API-Key aus der Umgebungsvariable `ANTHROPIC_API_KEY`, nie im Code oder Repo
- `pytest` für Tests, `ruff` für Lint und Format

## Wegweiser
- `src/jobagent/sources/`: Quellen als Adapter am Seam `Source`. Vor jeder Arbeit dort oder an den Fixtures: `docs/quellen.md`
- `src/jobagent/main.py`: der Lauf (suchen, dedupe, bewerten, Report) und `default_sources`, die die eingebauten Quellen aus der Konfiguration baut
- `src/jobagent/demo.py`: Demo-Lauf, im README zitiert; nur Fantasiefirmen und `example.com`
- `GLOSSARY.md`: Fachbegriffe mit ihrem Namen im Code
- `CODING_STANDARDS.md`: Ermessensregeln, gegen die jedes Review prüft
- `docs/adr/`: Grundsatzentscheidungen; vor Änderungen an Speicherung, Quellen, Rückkanal, Modellwahl oder Namen lesen
- `profile.md`: mein Suchprofil, nicht im Repo (Vorlage: `profile.example.md`)

## Befehle
- Tests: `pytest`
- Lint/Format: `ruff check . && ruff format .`
- Gesamtprobe ohne API-Key und Netz: `python -m jobagent.main --demo`
- Lauf: `python -m jobagent.main`
- Rückmeldung: `python -m jobagent.feedback --help`
- Profil-Vorschlag: `python -m jobagent.profile_suggestion`

## Konventionen
- Bezeichner und Dateinamen englisch nach der Spalte „Im Code“ in `GLOSSARY.md`; Texte für Menschen (Kommentare, Docstrings, Logs, Report, CLI-Ausgaben, Commits) deutsch mit den Glossar-Begriffen. Deutsch bleiben auch Feldnamen fremder APIs, Schlüssel in `config.toml`, das DB-Schema und die Bewertungs-Schlüssel gegenüber den Modellen, jeweils an genau einer Stelle übersetzt (ADR 0005)
- Bewertung liefert strikt JSON: `score` (1-5), `passt` (Liste), `passt_nicht` (Liste), `luecken` (Liste), `kurzfazit`
- Fehler einer Quelle dürfen den Lauf nicht abbrechen, sie werden geloggt und im Quellenstatus des Reports ausgewiesen
- Netzwerk und Modell sind in Tests immer ersetzt, nie live
- Eine Aufgabe pro Durchgang, danach committen

## Commits und Versionen
- Commit-Betreff: Imperativ, deutsch, mit echten Umlauten (ä/ö/ü/ß), max. ca. 70 Zeichen, keine Nummerierung wie „(Schritt n)“
- Commit-Text erklärt das Warum (Anlass, Auswirkung), nicht nur das Was
- Die Version steigt erst, wenn eine zusammenhängende Arbeit abgeschlossen ist, die meist mehrere Commits umfasst
- Version in `pyproject.toml` dann nach SemVer (0.x): neue Quelle oder Funktion → Minor, nur Fixes → Patch; `uv.lock` mitziehen
- Jede Versionsanhebung bekommt einen annotierten Tag `vX.Y.Z`

## Leitplanken
Begründungen stehen in den ADRs, hier nur die harten Grenzen:
- Gespeichert werden nur ID, Titel, Firma, Link, Score, Datum, Report, Treffernummer, Hash der Beschreibung und die Bewertung; Anzeigen-Volltexte bleiben flüchtig (ADR 0001)
- Anzeigen kommen nur über öffentliche Schnittstellen; LinkedIn, Xing und Indeed bleiben außen vor (ADR 0002)
- Der Agent liefert nur Vorschläge: Bewerbungen und Nachrichten schickt die Nutzerin selbst, den Bewerbungsstatus setzt nur sie, `profile.md` ändert sich erst nach ihrer ausdrücklichen Bestätigung (ADR 0003)

## Agent skills

### Issue tracker

GitHub Issues in `bettinawoste-wq/jobagent` via `gh`, blocking as native issue dependencies. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Worktree sessions

Sessions working in their own worktree whose work another session integrates: see `docs/agents/worktrees.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the root. See `docs/agents/domain.md`.
