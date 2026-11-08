# Job-Agent

Persönlicher Agent, der täglich (bzw. an festgelegten Tagen) neue, passende
Stellenanzeigen sucht, sie gegen ein individuelles Suchprofil bewertet und
eine Markdown-Datei mit den besten Treffern schreibt.

**Wichtig:** Der Agent schickt nie Bewerbungen oder Nachrichten ab — er
liefert ausschließlich Vorschläge zum manuellen Durchsehen.

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
- `pytest` (48 Tests, alles gemockt/mit Fixtures, kein Live-Zugriff in
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
