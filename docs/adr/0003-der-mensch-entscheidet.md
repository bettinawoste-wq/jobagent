---
status: accepted
---

# Der Mensch entscheidet, der Agent schlägt nur vor

## Kontext

Der Agent hat genug Wissen, um mehr zu tun als vorzuschlagen: Er kennt passende Anzeigen samt Link, das Suchprofil und den Bewerbungsstatus jeder Bewerbung. Technisch wäre es nicht weit bis zum automatischen Bewerben, zum Absage-Setzen nach langer Funkstille oder zum Umschreiben des Suchprofils aus dem Feedback. Jede dieser Handlungen wirkt aber nach außen oder auf persönliche Daten und lässt sich schlecht zurücknehmen. Eine abgeschickte Bewerbung bleibt abgeschickt.

## Entscheidung

Der Agent liefert nur Vorschläge, die Entscheidungen trifft der Mensch:

- **Keine automatischen Bewerbungen oder Nachrichten.** Der Agent schreibt Reports, er schickt nichts ab und nimmt keinen Kontakt auf.
- **Der Bewerbungsstatus ändert sich nur durch eigene Angabe**, nie von selbst, über das Kommando `python -m jobagent.feedback`. Auch eine Bewerbung, auf die lange keine Antwort kommt, wird nicht automatisch zur Absage. Stattdessen erinnert ein Nachfass-Hinweis im Report zeitlich begrenzt ans Nachhaken, der Bewerbungsstatus bleibt dabei unverändert.
- **Das Suchprofil ändert sich nur nach ausdrücklicher Bestätigung.** Ein Profil-Vorschlag wird als Diff gezeigt und erst nach einem „ja“ übernommen. Vorher wird eine Sicherung `profile.sicherung-….md` angelegt, die nie überschrieben wird. Das Modell liefert dabei nur einzelne Ersetzungen statt eines neuen Suchprofils, damit nichts unbemerkt verloren geht.

## Verworfene Alternativen

- **Automatisch bewerben.** Ausgeschlossen, seit dem ersten Commit in `CLAUDE.md` festgelegt.
- **Automatische Absage nach einer Frist ohne Antwort.** Bei der Planung des Rückkanals bewusst ausgeschlossen, ein ausführlicher Grund ist dazu nicht festgehalten. Er folgt aber aus der Grundregel: Ausbleibende Antwort ist noch keine Absage, und nur man selbst weiß, wie eine Bewerbung tatsächlich steht. Der Nachfass-Hinweis erinnert stattdessen ans Nachhaken.
- **Suchprofil direkt aus Feedback umschreiben.** Verworfen, weil `profile.md` nicht im Repo versioniert ist: Eine unbemerkte Änderung ließe sich nicht zurückholen. Dazu kommt, dass das Modell beim Auswerten von Feedback Lücken im Suchprofil von Lesefehlern der Bewertung trennen muss. Ein Lesefehler darf das Suchprofil nicht ändern, und ob das Modell richtig unterschieden hat, soll ein Mensch sehen.

## Konsequenzen

- Der Agent spart Zeit beim Suchen und Sortieren, nicht beim Bewerben. Jede Bewerbung bleibt Handarbeit.
- Der Bewerbungsstatus ist nur so aktuell, wie man ihn selbst pflegt. Wer keine Absagen einträgt, sieht diese Bewerbungen weiter als „beworben“.
- Ein Profil-Vorschlag braucht eine Sitzung am Terminal. Wird er abgebrochen, bleibt das Feedback offen und kommt beim nächsten Profil-Vorschlag wieder dran.
- Eine bestätigte Änderung am Suchprofil wirkt erst auf die Bewertung neuer Anzeigen in künftigen Läufen. Schon bewertete Anzeigen werden nicht neu bewertet.
