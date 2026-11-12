# Coding Standards

Gelesen beim Review. Was ein Werkzeug prüfen kann, prüft das Werkzeug (`ruff` mit Typannotationen für `src/`, CI). Hier stehen nur Ermessensfragen.

- **Kleine Funktionen**: Eine Funktion erledigt einen Schritt, den ihr Name benennt. Wächst sie über einen Bildschirm oder mischt sie Ablauf mit Detailarbeit, wird sie geteilt.
- **Sichtbare Seiteneffekte**: Netz, Dateien, Datenbank und Uhrzeit kommen über Parameter oder klar benannte Funktionen herein (für die Uhr prüft das `tests/test_clock_calls.py`). Eine Funktion, die rechnet, schreibt nicht nebenbei.
- **Glossar-Sprache**: Docstrings, Kommentare und Report-Texte benutzen die deutschen Glossar-Begriffe, nicht deren _Avoid_-Synonyme (ADR 0005). Dass Bezeichner englisch sind, prüft `tests/test_identifiers.py`.
- **Tests ohne Netz**: Jeder Zugriff auf Quellen oder Modell ist im Test ersetzt, über die Naht im Lauf (`sources`, `assess`, `config`) oder gemockte HTTP-Antworten aus `tests/fixtures/`.
