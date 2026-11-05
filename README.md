# Job-Agent

Persönlicher Agent, der täglich (bzw. an festgelegten Tagen) neue, passende
Stellenanzeigen sucht, sie gegen ein individuelles Suchprofil bewertet und
eine Markdown-Datei mit den besten Treffern schreibt.

**Wichtig:** Der Agent schickt nie Bewerbungen oder Nachrichten ab — er
liefert ausschließlich Vorschläge zum manuellen Durchsehen.

## Ablauf

```
Bundesagentur-Jobsuche-API
        │  (Suche + Jobdetails pro Treffer)
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
- `pytest` (32 Tests, alles gemockt/mit Fixtures, kein Live-Zugriff in
  Tests) und `ruff` für Lint/Format

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
Suchbegriffe).

## Verwenden

```bash
uv run python -m jobagent.main
```

Ergebnis landet in `output/YYYY-MM-DD.md`. Ohne neue Treffer wird eine kurze
Notiz statt einer leeren Datei geschrieben.

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
