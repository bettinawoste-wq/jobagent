# Job-Agent

Persönlicher Agent, der neue Stellenanzeigen sucht, gegen ein Suchprofil bewertet und Vorschläge zum manuellen Durchsehen liefert.

Texte für Menschen benutzen die deutschen Begriffe. Bezeichner und Dateinamen im Code benutzen den Namen unter _Im Code_ (ADR 0005).

## Suche

**Anzeige**:
Eine einzelne Veröffentlichung in einer Quelle, erkennbar an ihrer Quell-ID.
_Im Code_: `JobAd`
_Avoid_: Stellenbeschreibung

**Stelle**:
Die Position bei einer Firma, die hinter einer oder mehreren Anzeigen steht; gleiche Firma und gleicher Titel gelten als dieselbe Stelle, unabhängig von Quelle, Zeitpunkt und Schreibweise.
_Im Code_: `Position`, Schlüssel `position_key`
_Avoid_: Vakanz

**Textabweichung**:
Der Text einer Anzeige ist nicht exakt derselbe wie bei der früheren Anzeige derselben Stelle.
_Im Code_: `text_differs`
_Avoid_: Änderung, neue Version

**Quelle**:
Ein Anbieter, von dem Anzeigen kommen, etwa die Bundesagentur für Arbeit, Arbeitnow oder die Firmen-Watchlist.
_Im Code_: `Source`; Eigennamen bleiben erhalten: `BundesagenturSource`, `ArbeitnowSource`, `WatchlistSource`, `GreenhouseBoard`, `LeverBoard`
_Avoid_: Portal, Feed

**Suchbegriff**:
Ein Stichwort, nach dem in den Quellen gesucht wird; in `config.toml` als `was`.
_Im Code_: `keywords`
_Avoid_: Query, Filter

**Ort**:
Der Ort, um den herum gesucht wird; in `config.toml` als `wo`.
_Im Code_: `location`
_Avoid_: Region, Standort

## Bewertung

**Suchprofil**:
Die eigene Beschreibung von gesuchten Rollen, Stärken, Lücken und Ausschlüssen, gegen die Anzeigen bewertet werden.
_Im Code_: `SearchProfile`
_Avoid_: Profil, Lebenslauf

**Bewertung**:
Das Urteil des Modells zu einer Anzeige, bestehend aus Score, Passendem, Unpassendem, Lücken und Kurzfazit.
_Im Code_: `Assessment`
_Avoid_: Rating, Analyse

**Score**:
Die Passung einer Anzeige zum Suchprofil auf einer Skala von 1 bis 5; Bewerbungen und andere Umstände verändern ihn nicht.
_Im Code_: `score`
_Avoid_: Rang, Punkte

## Report

**Lauf**:
Ein Durchgang aus Suchen, Bewerten und Report-Schreiben, der genau einen Report erzeugt.
_Im Code_: `Run`
_Avoid_: Durchlauf, Testlauf

**Demo-Lauf**:
Ein Lauf mit erfundenen Anzeigen und vorgefertigten Bewertungen, der nichts aus dem Netz holt und nichts Persönliches liest oder speichert.
_Im Code_: `demo_run`
_Avoid_: Testlauf, Probelauf, Beispiellauf

**Report**:
Eine Datei mit den Treffern genau eines Laufs.
_Im Code_: `Report`
_Avoid_: Liste, Tagesdatei

**Treffer**:
Eine bewertete Anzeige in einem Report.
_Im Code_: `Match`
_Avoid_: Ergebnis, Vorschlag

**Treffernummer**:
Die Position eines Treffers innerhalb seines Reports; nur zusammen mit dem Report eindeutig.
_Im Code_: `match_number`
_Avoid_: ID, Rang

## Rückmeldung

**Bewerbung**:
Die Tatsache, dass man sich auf eine Stelle beworben hat, samt Datum.
_Im Code_: `Application`
_Avoid_: Kontakt

**Bewerbungsstatus**:
Der aktuelle Stand einer Bewerbung: beworben, Gespräch, Absage, Zusage oder zurückgezogen; er ändert sich nur durch eigene Angabe, nie von selbst.
_Im Code_: `ApplicationStatus`
_Avoid_: Phase, Zustand

**Nachfass-Hinweis**:
Eine zeitlich begrenzte Erinnerung im Report, bei einer Bewerbung ohne Antwort nachzuhaken; sie verändert den Bewerbungsstatus nicht.
_Im Code_: `FollowUpReminder`
_Avoid_: Mahnung, Wiedervorlage

**Feedback**:
Der eigene Score zu einem Treffer, optional mit einem Grund.
_Im Code_: `Feedback`
_Avoid_: Korrektur, Kommentar

**Profil-Vorschlag**:
Eine aus Feedback abgeleitete Änderung am Suchprofil, die erst nach ausdrücklicher Bestätigung gilt.
_Im Code_: `ProfileSuggestion`
_Avoid_: Profil-Update, automatische Anpassung
