# Startprompts für Claude Code

> **Historisch.** Mit diesen Prompts ist Version 0.1 entstanden. Datei- und Funktionsnamen (`fetch.py`, `search(was, …)`, `mark_seen(anzeige)`) entsprechen nicht mehr dem Code; maßgeblich sind `CLAUDE.md`, `GLOSSARY.md` und `docs/`.

Vorbereitung: leeren Ordner anlegen, `git init`, diese drei Dateien hineinkopieren, `claude` starten. Zuerst Plan Mode (Shift+Tab), Plan lesen, erst dann umsetzen lassen. Nach jedem Schritt Tests laufen lassen und committen.

## Schritt 0: Plan
Lies CLAUDE.md und profile.md. Erstelle einen Umsetzungsplan in fünf kleinen Schritten (Projektgerüst, Fetch, Store, Score, Report). Noch keinen Code schreiben. Nenne offene Fragen.

## Schritt 1: Projektgerüst
Lege die Struktur aus CLAUDE.md an: pyproject.toml, src/jobagent, tests, .gitignore (inkl. output/, .env, *.db). Richte pytest und ruff ein. Ein Dummy-Test muss grün laufen.

## Schritt 2: Fetch
Implementiere fetch.py für die Jobsuche-API der Bundesagentur. Prüfe Endpunkt und Header in der Doku von bundesAPI/jobsuche-api. Funktion: search(was, wo, umkreis, veroeffentlichtseit) gibt eine Liste einfacher Datenobjekte zurück (id, titel, firma, ort, link, beschreibung falls vorhanden). Schreibe zuerst Tests mit einer gespeicherten Beispielantwort in tests/fixtures, ohne Live-Zugriff.

## Schritt 3: Store
Implementiere store.py mit SQLite: is_new(id), mark_seen(anzeige). Tests mit temporärer Datenbank.

## Schritt 4: Score
Implementiere score.py: Eine Anzeige plus profile.md gehen an die Anthropic API (Modell Haiku), Antwort strikt als JSON laut CLAUDE.md. Validiere die Antwort, behandle Fehler robust. Teste mit gemocktem Client. Danach drei echte Anzeigen von mir manuell bewerten lassen, damit wir den Prompt gemeinsam nachjustieren.

## Schritt 5: Report und Ablauf
Implementiere report.py (output/YYYY-MM-DD.md, sortiert nach Score, pro Treffer Titel, Firma, Ort, Link, Score, Gründe, Lücken) und main.py. Suchbegriffe kommen aus einer config.toml. Ein Lauf ohne neue Treffer erzeugt eine kurze Notiz statt einer leeren Datei.

## Schritt 6: Täglich ausführen
Zeige mir, wie ich main.py per cron (oder launchd/Task Scheduler) täglich morgens starten lasse. Noch nichts am System ändern, nur Anleitung.
