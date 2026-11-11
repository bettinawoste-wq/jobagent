# Job-Agent

Persönlicher Agent, der täglich neue, passende Stellenanzeigen sucht, gegen mein Profil bewertet und eine Markdown-Datei mit den besten Treffern schreibt. Er schickt nie Bewerbungen oder Nachrichten ab, er liefert nur Vorschläge.

## Stack
- Python 3.12, Abhängigkeiten per `uv` (oder `pip` + `venv`)
- `httpx` für HTTP, `sqlite3` aus der Standardbibliothek für Dedupe
- `anthropic` SDK für die Bewertung (Modell Haiku) und den seltenen Profil-Vorschlag (Modell Sonnet), API-Key aus Umgebungsvariable `ANTHROPIC_API_KEY`, nie im Code oder Repo
- `pytest` für Tests, `ruff` für Lint und Format

## Struktur
- `src/jobagent/sources/`: Quellen am Seam `Source` (`name`, `search(keywords) -> SearchResult`); je Quelle ein Adapter, der alle Suchbegriffe auf einmal bekommt, intern dedupliziert und nie wirft. Fertig: `bundesagentur.py` (`BundesagenturSource`). Intern: `_http.py` (JSON-Abruf mit Fehlergrund), `_legacy.py` (Übergangsadapter für Arbeitnow und Watchlist)
- `src/jobagent/fetch.py`: alter Quellen-Code für Arbeitnow und Firmen-Watchlist via Greenhouse/Lever, hängt übergangsweise per `_legacy.py` am Seam
- `src/jobagent/store.py`: SQLite, merkt sich gesehene Anzeigen samt Report, Treffernummer, Hash und Bewertung
- `src/jobagent/score.py`: Bewertung einer Anzeige gegen `profile.md`, strukturierte JSON-Antwort
- `src/jobagent/report.py`: schreibt `output/YYYY-MM-DD.md` (weitere Läufe am Tag: `-2`, `-3`, nie überschreiben), sortiert nach Score, unter `mindest_score` nur einzeilig, bereits beworbene Stellen im eigenen Block am Ende
- `src/jobagent/main.py`: Ablauf: suchen (Liste von `Source`), dedupe, score, report; `default_sources` baut die eingebauten Quellen aus der Konfiguration
- `src/jobagent/config.py`: liest `config.toml` und übersetzt die deutschen Schlüssel an genau dieser Stelle
- `src/jobagent/feedback.py`: Kommando für Bewerbungen, Bewerbungsstatus und eigenen Score
- `src/jobagent/job_ad.py`: die Anzeige (`JobAd`)
- `src/jobagent/position.py`: erkennt dieselbe Stelle über normalisierte Firma + Titel (`position_key`)
- `src/jobagent/profile_suggestion.py`: leitet aus Feedback Änderungen an `profile.md` ab (Diff, Bestätigung, Sicherung)
- `src/jobagent/demo.py`: Demo-Lauf mit erfundenen Anzeigen und vorgefertigten Bewertungen (öffentlich, im README zitiert: nur Fantasiefirmen und `example.com`)
- `tests/`: Tests, Beispielantworten liegen in `tests/fixtures/`
- `profile.md`: mein Suchprofil und meine Ausschlusskriterien
- `GLOSSARY.md`: Fachbegriffe (Anzeige, Stelle, Treffer, Lauf …) mit ihrem Namen im Code; Namen in Code, Tickets und Texten folgen ihm
- `docs/adr/`: Grundsatzentscheidungen mit Begründung; vor Änderungen an Speicherung, Quellen, Rückkanal oder Modellwahl lesen

## Befehle
- Tests: `pytest`
- Lint/Format: `ruff check . && ruff format .`
- Gesamtprobe ohne API-Key und Netz: `python -m jobagent.main --demo`
- Lauf: `python -m jobagent.main`
- Rückmeldung: `python -m jobagent.feedback --help`
- Profil-Vorschlag: `python -m jobagent.profile_suggestion`

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

## Quelle 3: Firmen-Watchlist (Greenhouse/Lever)
- Statt breiter Suche: konkrete Firmen aus `config.toml` (`[[firmen]]`, Felder `name`/`ats`/`slug`) werden direkt über ihr öffentliches Jobboard durchsucht.
- Greenhouse (`boards-api.greenhouse.io/v1/boards/{slug}/jobs`): Beschreibung kommt doppelt HTML-escaped und braucht einen Detail-Call pro Treffer (`?content=true`).
- Lever (`api.lever.co/v0/postings/{slug}`): liefert direkt `descriptionPlain`, kein HTML-Stripping nötig. Response ist eine rohe Liste, kein Wrapper-Objekt.
- Beide ohne serverseitige Stichwortsuche - Filterung nach `was` passiert clientseitig in `fetch.search_greenhouse`/`fetch.search_lever`. Scheitert eine Firma, werden die übrigen trotzdem durchsucht (`fetch.search_watchlist`).
- Netzwerkzugriffe in Tests immer mocken, nie live testen.
- Bewusst nicht genutzt: Remotive-API - Suchparameter filtert praktisch nicht, winziger kaum Deutschland-relevanter Feed, und die API-Antwort selbst weist auf ein kostenpflichtiges Angebot für diesen Nutzungszweck hin.

## Konventionen
- Bezeichner und Dateinamen englisch nach der Spalte „Im Code“ in `GLOSSARY.md`; Texte für Menschen (Kommentare, Docstrings, Logs, Report, CLI-Ausgaben, Commits) deutsch mit den Glossar-Begriffen. Feldnamen fremder APIs, Schlüssel in `config.toml` und das DB-Schema bleiben, wie sie sind (ADR 0005)
- Bewertung liefert strikt JSON: `score` (1-5), `passt` (Liste), `passt_nicht` (Liste), `luecken` (Liste), `kurzfazit`
- Fehler einer Quelle dürfen den Lauf nicht abbrechen, sie werden geloggt und im Quellenstatus des Reports ausgewiesen
- Eine Aufgabe pro Durchgang, danach committen

## Commits und Versionen
- Commit-Betreff: Imperativ, deutsch, mit echten Umlauten (ä/ö/ü/ß), max. ca. 70 Zeichen, keine Nummerierung wie „(Schritt n)“
- Commit-Text erklärt das Warum (Anlass, Auswirkung), nicht nur das Was
- Nicht jeder Commit ist eine neue Version: Die Version steigt erst, wenn eine zusammenhängende Arbeit abgeschlossen ist, die meist mehrere Commits umfasst
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

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the root. See `docs/agents/domain.md`.
