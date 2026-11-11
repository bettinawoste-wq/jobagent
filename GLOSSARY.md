# Job-Agent

Persönlicher Agent, der neue Stellenanzeigen sucht, gegen ein Suchprofil bewertet und Vorschläge zum manuellen Durchsehen liefert.

## Suche

**Anzeige**:
Eine einzelne Veröffentlichung in einer Quelle, erkennbar an ihrer Quell-ID.
_Avoid_: Job, Posting, Stellenbeschreibung

**Stelle**:
Die Position bei einer Firma, die hinter einer oder mehreren Anzeigen steht; gleiche Firma und gleicher Titel gelten als dieselbe Stelle, unabhängig von Quelle, Zeitpunkt und Schreibweise.
_Avoid_: Job, Vakanz

**Textabweichung**:
Der Text einer Anzeige ist nicht exakt derselbe wie bei der früheren Anzeige derselben Stelle.
_Avoid_: Änderung, neue Version

**Quelle**:
Ein Anbieter, von dem Anzeigen kommen, etwa die Bundesagentur für Arbeit, Arbeitnow oder die Firmen-Watchlist.
_Avoid_: Portal, Feed

## Bewertung

**Suchprofil**:
Die eigene Beschreibung von gesuchten Rollen, Stärken, Lücken und Ausschlüssen, gegen die Anzeigen bewertet werden.
_Avoid_: Profil, Lebenslauf

**Bewertung**:
Das Urteil des Modells zu einer Anzeige, bestehend aus Score, Passendem, Unpassendem, Lücken und Kurzfazit.
_Avoid_: Rating, Analyse

**Score**:
Die Passung einer Anzeige zum Suchprofil auf einer Skala von 1 bis 5; Bewerbungen und andere Umstände verändern ihn nicht.
_Avoid_: Rang, Punkte

## Report

**Lauf**:
Ein Durchgang aus Suchen, Bewerten und Report-Schreiben, der genau einen Report erzeugt.
_Avoid_: Durchlauf, Job, Testlauf

**Demo-Lauf**:
Ein Lauf mit erfundenen Anzeigen und vorgefertigten Bewertungen, der nichts aus dem Netz holt und nichts Persönliches liest oder speichert.
_Avoid_: Testlauf, Probelauf, Beispiellauf

**Report**:
Eine Datei mit den Treffern genau eines Laufs.
_Avoid_: Liste, Tagesdatei

**Treffer**:
Eine bewertete Anzeige in einem Report.
_Avoid_: Ergebnis, Vorschlag

**Treffernummer**:
Die Position eines Treffers innerhalb seines Reports; nur zusammen mit dem Report eindeutig.
_Avoid_: ID, Rang

## Rückmeldung

**Bewerbung**:
Die Tatsache, dass man sich auf eine Stelle beworben hat, samt Datum.
_Avoid_: Application, Kontakt

**Bewerbungsstatus**:
Der aktuelle Stand einer Bewerbung: beworben, Gespräch, Absage, Zusage oder zurückgezogen; er ändert sich nur durch eigene Angabe, nie von selbst.
_Avoid_: Phase, Zustand

**Nachfass-Hinweis**:
Eine zeitlich begrenzte Erinnerung im Report, bei einer Bewerbung ohne Antwort nachzuhaken; sie verändert den Bewerbungsstatus nicht.
_Avoid_: Mahnung, Wiedervorlage

**Feedback**:
Der eigene Score zu einem Treffer, optional mit einem Grund.
_Avoid_: Korrektur, Kommentar

**Profil-Vorschlag**:
Eine aus Feedback abgeleitete Änderung am Suchprofil, die erst nach ausdrücklicher Bestätigung gilt.
_Avoid_: Profil-Update, automatische Anpassung
