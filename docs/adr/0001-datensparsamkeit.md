---
status: accepted
---

# Keine Volltexte von Anzeigen speichern

## Kontext

Der Agent merkt sich jede gesehene Anzeige in einer lokalen SQLite-Datenbank, damit sie im nächsten Lauf nicht erneut bewertet wird. Seit dem Rückkanal (Version 0.3.0) braucht er mehr als nur die ID: Feedback und Bewerbungen sprechen einen Treffer über Report und Treffernummer an, und erscheint eine Stelle erneut, auf die man sich schon beworben hat, soll der Report sagen, ob es eine Textabweichung gegenüber der Anzeige bei der Bewerbung gibt.

Am einfachsten wäre es, die Beschreibung jeder Anzeige komplett abzulegen. Dagegen steht eine Regel, die seit dem ersten Commit in `CLAUDE.md` gilt: keine Anzeigen-Volltexte dauerhaft speichern. Ein ausdrücklicher Grund ist dort nicht festgehalten. Naheliegend ist, dass die Texte den inserierenden Firmen gehören und der Agent für seinen Zweck nur ein Urteil über eine Anzeige braucht, keine Kopie von ihr.

## Entscheidung

Von jeder Anzeige werden nur gespeichert: ID, Titel, Firma, Link, Score, Datum, Report, Treffernummer, ein SHA-256-Hash der Beschreibung und die Bewertung des Modells (`passt`, `passt_nicht`, `luecken`, `kurzfazit`). Der Volltext der Beschreibung wird nie dauerhaft gespeichert, er existiert nur während eines Laufs im Speicher.

Eine Textabweichung wird über den Hash erkannt: Vor dem Hashen wird Leerraum vereinheitlicht, damit reine Formatierung nicht als Abweichung zählt (`store.beschreibung_hash`).

## Verworfene Alternativen

- **Volltext speichern und vergleichen.** Damit ließe sich zeigen, *was* sich geändert hat. Verworfen, weil es die Regel brechen würde. Beim Ausbau des Stores wurde die Regel um Hash und Bewertung erweitert, das Verbot von Volltexten blieb bewusst bestehen.
- **Gar nichts außer der ID speichern.** So war der Store bis Version 0.2.0. Für Feedback, Bewerbungen und den Vergleich bei erneut erscheinenden Stellen reicht das nicht mehr.

## Konsequenzen

- Der Report kann nur „Text identisch“, „Text weicht von deiner Bewerbung ab“ oder „Text nicht vergleichbar“ melden, aber nicht zeigen, welche Stelle im Text sich geändert hat.
- Schon ein einzelnes geändertes Wort gilt als Textabweichung. Ob eine Abweichung inhaltlich wichtig ist, muss man selbst in der Anzeige nachlesen.
- Eine gespeicherte Anzeige lässt sich später nicht neu bewerten, etwa nach einer Änderung am Suchprofil, weil der Text dafür fehlt. Dafür müsste die Anzeige erneut von der Quelle geholt werden.
- Datenbanken aus Version 0.2.0 bekommen die neuen Spalten beim Öffnen ergänzt. Für alte Zeilen bleiben sie leer, ihr Text ist also „nicht vergleichbar“.
- Die Bewertung des Modells wird mitgespeichert, weil der Profil-Vorschlag sie neben dem Feedback braucht. Sie ist eine kurze, vom Modell formulierte Einschätzung, keine Kopie der Anzeige.
