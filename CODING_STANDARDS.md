# Coding Standards

Gelesen beim Review. Was ein Werkzeug prüfen kann, prüft das Werkzeug (`ruff` mit Typannotationen für `src/`, CI). Hier stehen nur Ermessensfragen.

- **Kleine Funktionen**: Eine Funktion erledigt einen Schritt, den ihr Name benennt. Wächst sie über einen Bildschirm oder mischt sie Ablauf mit Detailarbeit, wird sie geteilt.
- **Sichtbare Seiteneffekte**: Netz, Dateien, Datenbank und Uhrzeit kommen über Parameter oder klar benannte Funktionen herein. Eine Funktion, die rechnet, schreibt nicht nebenbei.
- **Glossar-Sprache**: Bezeichner, Docstrings und Report-Texte benutzen die Begriffe aus `GLOSSARY.md`, nicht deren _Avoid_-Synonyme.
- **Tests ohne Netz**: Jeder Zugriff auf Quellen oder Modell ist im Test ersetzt, über die Naht im Lauf (`quellen`, `bewerte`, `konfig`) oder gemockte HTTP-Antworten aus `tests/fixtures/`.
