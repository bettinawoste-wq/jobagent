---
status: accepted
---

# Haiku für die Bewertung, Sonnet für den Profil-Vorschlag

## Kontext

Der Agent ruft an zwei Stellen ein Sprachmodell auf, und die beiden Aufgaben sind sehr verschieden:

- **Bewertung** (`score.py`): In jedem Lauf wird jede neue Anzeige einzeln gegen das Suchprofil bewertet, also ein Aufruf pro Anzeige. Die Antwort ist klein und fest vorgegeben: Score von 1 bis 5, Listen für Passendes, Unpassendes und Lücken, ein kurzes Fazit.
- **Profil-Vorschlag** (`profilvorschlag.py`): Läuft nur, wenn man ihn selbst startet. Ein einziger Aufruf wertet alles offene Feedback zusammen mit den früheren Bewertungen aus. Dabei muss das Modell unterscheiden, ob eine Abweichung zwischen Score und eigenem Score auf eine Lücke im Suchprofil zurückgeht oder auf einen Lesefehler der Bewertung, und es soll das Suchprofil nur im ersten Fall ändern.

## Entscheidung

- Die **Bewertung** nutzt Claude Haiku. Die Antwort wird über ein Werkzeug mit festem Schema erzwungen (`tool_choice`) und danach noch einmal geprüft. Eine ungültige Antwort wird geloggt, die Anzeige wird im nächsten Lauf erneut versucht.
- Der **Profil-Vorschlag** nutzt Claude Sonnet, mit großzügigem Antwortbudget und strukturierter JSON-Antwort.

## Verworfene Alternativen

- **Sonnet auch für die Bewertung.** Nicht gewählt. Die Bewertung ist der häufige Aufruf, Kosten und Wartezeit pro Aufruf zählen dort mal der Zahl neuer Anzeigen. Haiku war von Anfang an als Modell für die Bewertung festgelegt. Ein Vergleich der Bewertungsqualität beider Modelle oder eine Kostenmessung ist nicht dokumentiert.
- **Haiku auch für den Profil-Vorschlag.** Nicht gewählt. Der Profil-Vorschlag ist selten, aber anspruchsvoller: Er muss im gesamten offenen Feedback Muster erkennen und Lesefehler von echten Lücken trennen, und ein Fehler landet nach Bestätigung im Suchprofil. Ein direkter Vergleich mit Haiku für diese Aufgabe ist nicht dokumentiert.

## Konsequenzen

- Die Zahl der Modellaufrufe wächst mit der Zahl neuer Anzeigen pro Lauf, also mit Suchbegriffen und Quellen. Der Profil-Vorschlag fällt daneben kaum ins Gewicht, weil er selten und als einzelner Aufruf läuft.
- Die Bewertung liest gelegentlich falsch, das zeigte bereits ein echter Lauf. Deshalb trennt der Profil-Vorschlag Lesefehler der Bewertung von Lücken im Suchprofil, statt jede Abweichung ins Suchprofil zu übernehmen.
- Die Modellnamen stehen jeweils als Konstante `_MODEL` in `score.py` und `profilvorschlag.py`. Ein Wechsel ist dort schnell gemacht. Die Tests prüfen nur das Antwortformat gegen gefälschte Antworten, nicht die Qualität des Urteils, deshalb gehört nach einem Wechsel ein echter Lauf dazu.
