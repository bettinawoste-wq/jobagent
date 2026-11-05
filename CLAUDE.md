# Job-Agent

Persönlicher Agent, der täglich neue, passende Stellenanzeigen sucht, gegen mein Profil bewertet und eine Markdown-Datei mit den besten Treffern schreibt. Er schickt nie Bewerbungen oder Nachrichten ab, er liefert nur Vorschläge.

## Stack
- Python 3.12, Abhängigkeiten per `uv` (oder `pip` + `venv`)
- `httpx` für HTTP, `sqlite3` aus der Standardbibliothek für Dedupe
- `anthropic` SDK für die Bewertung (Modell Haiku, API-Key aus Umgebungsvariable `ANTHROPIC_API_KEY`, nie im Code oder Repo)
- `pytest` für Tests, `ruff` für Lint und Format

## Struktur
- `src/jobagent/fetch.py`: Anzeigen von Quellen holen (Bundesagentur für Arbeit, Arbeitnow)
- `src/jobagent/store.py`: SQLite, merkt sich gesehene Anzeigen-IDs
- `src/jobagent/score.py`: Bewertung einer Anzeige gegen `profile.md`, strukturierte JSON-Antwort
- `src/jobagent/report.py`: schreibt `output/YYYY-MM-DD.md`, sortiert nach Score
- `src/jobagent/main.py`: Ablauf: fetch, dedupe, score, report
- `tests/`: Tests, Beispielantworten liegen in `tests/fixtures/`
- `profile.md`: mein Suchprofil und meine Ausschlusskriterien

## Befehle
- Tests: `pytest`
- Lint/Format: `ruff check . && ruff format .`
- Lauf: `python -m jobagent.main`

## Quelle 1: Jobsuche-API der Bundesagentur für Arbeit
- Doku und Beispiele: GitHub `bundesAPI/jobsuche-api`. Endpunkt, Header und Parameter immer dort gegenprüfen, nicht raten.
- Achtung: Die Live-API (`pc/v6/jobs`) weicht vom dokumentierten Schema ab (z. B. `ergebnisliste` statt `stellenangebote`, `referenznummer` statt `refnr`) - immer gegen echte Antworten verifizieren, nicht nur gegen die Doku.
- Suche nach Stichwort (`was`), Ort (`wo`), Umkreis (`umkreis`), Alter der Anzeige (`veroeffentlichtseit`).
- Netzwerkzugriffe in Tests immer mocken, nie live testen.

## Quelle 2: Arbeitnow API
- Kostenlose, öffentliche API ohne Key: `https://www.arbeitnow.com/api/job-board-api`. Aggregiert Remote-/Europa-Jobs (Tech-Schwerpunkt).
- Keine serverseitige Stichwort- oder Ortssuche - Filterung nach `was`/`wo` passiert clientseitig in `fetch.search_arbeitnow`. Kein `umkreis` möglich (keine Geokoordinaten).
- Paging folgt `links.next`, stoppt sobald Einträge älter als `veroeffentlichtseit` Tage auftauchen (max. 10 Seiten als Sicherheitsgrenze - maßvolle Nutzung der freien API).
- Netzwerkzugriffe in Tests immer mocken, nie live testen.

## Konventionen
- Kleine Funktionen, Typannotationen, keine versteckten Seiteneffekte
- Bewertung liefert strikt JSON: `score` (1-5), `passt` (Liste), `passt_nicht` (Liste), `luecken` (Liste), `kurzfazit`
- Fehler einer Quelle dürfen den Lauf nicht abbrechen, sie werden geloggt
- Eine Aufgabe pro Durchgang, danach committen

## Nicht tun
- Keine Anzeigen-Volltexte dauerhaft speichern, nur ID, Titel, Firma, Link, Score, Datum
- Keine Scraper für Seiten, die automatisiertes Auslesen untersagen (LinkedIn, Xing, Indeed)
- Keine automatischen Bewerbungen oder Nachrichten
