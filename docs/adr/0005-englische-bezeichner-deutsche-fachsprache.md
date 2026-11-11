---
status: accepted
---

# Englische Bezeichner, deutsche Fachsprache

## Kontext

Bisher folgten alle Namen dem deutschen Glossar, auch im Code: `profilvorschlag.py`, `bewerte`, `quellen`, `konfig`. Dazwischen stehen englische Namen aus Python, den Bibliotheken und den fremden APIs, sodass sich in vielen Zeilen beide Sprachen mischen. Mit dem anstehenden Umbau der Quellen zu einer gemeinsamen Schnittstelle (`Source`) entstehen viele neue Namen, und für jeden müsste neu entschieden werden, in welcher Sprache er steht.

Gleichzeitig ist die Fachsprache deutsch und soll es bleiben: Das Suchprofil, die Reports, die Kommandos und die Anzeigen der Bundesagentur sind deutsch, und das Glossar legt fest, was ein Treffer, eine Stelle oder ein Lauf ist.

## Entscheidung

- **Bezeichner sind englisch**: Variablen, Funktionen, Klassen, Module, Dateien und Testnamen. Jeder Begriff im Glossar bekommt dafür einen festen Namen unter _Im Code_, etwa Anzeige = `JobAd`, Treffer = `Match`, Profil-Vorschlag = `ProfileSuggestion`. Eigennamen bleiben erhalten (`BundesagenturSource`).
- **Texte für Menschen sind deutsch** und benutzen die Glossar-Begriffe: Kommentare, Docstrings, Log-Meldungen, Report-Inhalt, CLI-Ausgaben, Fehlergründe im Quellenstatus und Commits.
- **Fremde Feldnamen bleiben, wie sie kommen.** Was eine API liefert (`referenznummer`, `descriptionPlain`), wird nicht übersetzt.
- **`config.toml` und das Datenbankschema bleiben deutsch.** Sie werden an genau einer Stelle übersetzt, beim Laden der Konfiguration bzw. im `store`. So funktionieren bestehende Konfiguration und Daten ohne Migration weiter.
- **Erst umbenennen, dann umbauen.** Die Umbenennung kommt als eigener, mechanischer Schritt, bei dem die Tests grün bleiben. Der Umbau der Quellen folgt danach.

## Verworfene Alternativen

- **Nur neuer Code englisch.** Nicht gewählt. Der bestehende Code bliebe deutsch, und der Bruch liefe quer durch die Module: `store` und `report` deutsch, `sources` englisch. Für jeden Namen müsste man wissen, wann er entstanden ist, und die Mischung, die die Entscheidung beseitigen soll, bliebe dauerhaft.
- **Umbenennen und Quellen-Umbau in einem Schritt.** Nicht gewählt. Ein Diff, der zugleich Namen und Struktur ändert, lässt sich kaum prüfen: Eine Verhaltensänderung verschwindet zwischen Hunderten umbenannter Zeilen. Getrennt bleibt die Umbenennung mechanisch, und die Tests zeigen, dass sie nichts verändert hat.

## Konsequenzen

- Das Glossar bleibt die Quelle für Namen in beiden Sprachen. Ein neuer Begriff bekommt dort seinen deutschen Namen und seinen Namen im Code, bevor er im Code auftaucht.
- Englische Wörter, die jetzt Code-Namen sind (etwa Job, Posting, Application), stehen nicht mehr in den _Avoid_-Listen. In Texten für Menschen gilt weiter der deutsche Begriff.
- Wo `config.toml` oder die Datenbank gelesen und geschrieben werden, stehen deutsche Schlüssel neben englischen Namen. Diese Übersetzung ist gewollt und bleibt auf diese zwei Stellen beschränkt.
- Die ADRs 0001 bis 0004 nennen noch die alten Datei- und Funktionsnamen, etwa `profilvorschlag.py`. Sie halten den Stand ihrer Entscheidung fest und werden nicht nachgezogen.
