# Quellen: API-Details und Fallstricke

Diese Datei brauchst du vor jeder Arbeit an `src/jobagent/sources/` oder an den Fixtures in `tests/fixtures/`. Welche Quellen erlaubt sind und warum, steht in ADR 0002.

Jede Quelle ist ein Adapter am Seam `Source` und erfüllt `name` und `search(keywords) -> SearchResult`:
- Sie bekommt alle Suchbegriffe auf einmal.
- Sie dedupliziert intern.
- Sie wirft nie. Fehler meldet sie im `SearchResult` in der Form „<Suchbegriff oder Firma>: <Grund>“.
- Sie liefert in `JobAd` nur Text oder `None`:
  - Hat ein Pflichtfeld (Titel, Link) den falschen Typ, fällt nur dieser Eintrag weg. Gemeldet wird einmal „ungültige Antwort“, die übrigen Anzeigen bleiben. Fehlt das Feld, bleibt es "". Hat die Quelle einen Ersatz (Bundesagentur: Titel aus `hauptberuf`, Link aus der Referenznummer), greift dieser bei fehlendem Feld und bei falschem Typ. Bleibt nach einem falschen Typ kein Titel übrig, fällt der Eintrag weg. Quellen, die lokal auf den Titel filtern (Arbeitnow, Watchlist), verwerfen einen Titel mit falschem Typ ohne Meldung: Er kann kein Treffer sein.
  - Hat ein optionales Feld (Firma, Ort, Beschreibung) oder sein Unterobjekt den falschen Typ, wird nur dieses Feld `None`, auch wenn es in einem Container wie dem Ort-Unterobjekt steckt. Die Anzeige bleibt, gemeldet wird nichts. Welche Pfade das je Quelle sind, nennt der Vertragstest.
  - Ein Eintrag ohne gültige ID macht dagegen die ganze Antwort ungültig.

Der Vertragstest `tests/sources/test_contract.py` prüft das für jeden Adapter: Jeder nennt dort seine optionalen Pfade als Präfixe (`("ergebnisliste", 0, "stellenlokationen")` deckt alles darunter), auch Felder mit Ersatz und aus Detail-Abrufen. Eine neue Quelle trägt ihre optionalen Pfade dort ein.

Der JSON-Abruf mit Fehlergrund, die Typprüfung der Felder (auch `text_at` für Textfelder unter einem Pfad durch Unterobjekte und Listen) und die HTML-zu-Text-Umwandlung liegen einmal in `_http.py`. Die IDs der Anzeigen bleiben stabil, weil die Datenbank an ihnen hängt.

## Bundesagentur für Arbeit (`BundesagenturSource`)
- Doku und Beispiele stehen im GitHub-Projekt `bundesAPI/jobsuche-api`. Endpunkt, Header und Parameter immer dort gegenprüfen.
- Die Live-API (`pc/v6/jobs`) weicht vom dokumentierten Schema ab, zum Beispiel `ergebnisliste` statt `stellenangebote` und `referenznummer` statt `refnr`. Feldnamen gegen echte Antworten verifizieren, nicht nur gegen die Doku.
- Suchparameter:
  - Stichwort (`was` unter `[suche]`)
  - Ort (`wo` unter `[suche]`)
  - Umkreis (`umkreis` unter `[bundesagentur]`, nur diese Quelle nutzt ihn)
  - Alter der Anzeige (`veroeffentlichtseit` der API) aus dem Suchzeitraum, siehe `GLOSSARY.md`; `veroeffentlichtseit` unter `[suche]` ist nur dessen Startwert und Höchstwert
- Blättern laut Doku: `page` (ab 1) und `size`; die Antwort nennt die Gesamtzahl in `maxErgebnisse` (Doku: Text, Beispielantwort: Zahl). Je Suchbegriff blättert die Quelle mit 50 Ergebnissen je Seite, höchstens 5 Seiten. Nennt die Antwort `maxErgebnisse`, endet das Blättern, sobald so viele verschiedene Anzeigen da sind; eine kürzere Seite allein beendet es dann nicht. Ohne `maxErgebnisse` endet es an der ersten nicht vollen Seite. Eine Seite ohne neue Anzeigen (leer oder nur Wiederholungen) beendet es immer. Wie die Live-API Seiten hinter dem Ende beantwortet, ist nicht dokumentiert. Bleiben danach Ergebnisse übrig, meldet sie „Ergebnisse abgeschnitten nach 5 Seiten“ als Fehler; der Lauf zählt dann nicht als vollständig. Die Grenze ist maßvoll gewählt, weil jede gefundene Anzeige noch einen Detail-Call kostet.
- Die Beschreibung kommt per Detail-Call, einmal je Anzeige.
- Die ID ist die rohe `referenznummer`.

## Arbeitnow (`ArbeitnowSource`)
- Freie, öffentliche API ohne Key: `https://www.arbeitnow.com/api/job-board-api`. Sie sammelt Remote- und Europa-Jobs mit Tech-Schwerpunkt.
- Es gibt keine serverseitige Suche nach Stichwort oder Ort. Gefiltert wird lokal, und alle Suchbegriffe teilen sich dieselben abgerufenen Seiten. Der Ort (`wo` unter `[suche]`) wird lokal im Ort-Feld gesucht. Ein `umkreis` ist nicht möglich, weil die API keine Geokoordinaten liefert.
- Das Paging folgt `links.next` und stoppt nach der ersten Seite, auf der jede Anzeige älter als der Suchzeitraum ist. Eine einzelne alte Anzeige reicht nicht: Die Live-API sortiert nicht streng nach Datum, im November 2026 standen auf Seite 1 Anzeigen von 1,7 Tagen und auf Seite 4 noch welche von wenigen Stunden. Höchstens 10 Seiten pro Lauf, als Sicherheitsgrenze und zur maßvollen Nutzung der freien API. Gibt es nach der zehnten Seite noch eine nächste, meldet die Quelle „Ergebnisse abgeschnitten nach 10 Seiten“ als Fehler.
- Das Veröffentlichungsdatum `created_at` zählt nur als Zahl. Fehlt es oder hat es einen anderen Typ, auch einen Wahrheitswert, oder ist es keine endliche Zahl (NaN, Infinity), gilt die Anzeige nicht als zu alt.
- Die Uhr kommt über den Konstruktor (`now`).
- Die ID hat die Form `arbeitnow:<slug>`.

## Firmen-Watchlist (`WatchlistSource`)
- Statt einer breiten Suche werden konkrete Firmen aus `config.toml` direkt über ihr öffentliches Jobboard durchsucht:
  - Sie stehen dort als `[[watchlist.firmen]]` mit `name`, `ats` und `slug`.
  - Im Code heißen sie `WatchlistCompany`.
- Jedes Board wird pro Lauf einmal abgefragt, die Suchbegriffe werden lokal auf den Titel gefiltert. Von `[suche]` nutzt die Watchlist nur `was`, nicht `wo` und nicht `veroeffentlichtseit`; einen Suchzeitraum kennt sie nicht.
- Scheitert eine Firma, werden die übrigen trotzdem durchsucht.
- **Greenhouse** (`GreenhouseBoard`):
  - Abruf über `boards-api.greenhouse.io/v1/boards/{slug}/jobs`.
  - Die Beschreibung kommt doppelt HTML-escaped und braucht pro Treffer einen Detail-Call (`?content=true`).
  - Die ID hat die Form `greenhouse:<slug>:<id>`.
- **Lever** (`LeverBoard`):
  - Abruf über `api.lever.co/v0/postings/{slug}`.
  - Die Antwort ist eine rohe Liste, kein Wrapper-Objekt.
  - Die Beschreibung kommt direkt als `descriptionPlain` und braucht kein HTML-Stripping.
  - Die ID hat die Form `lever:<slug>:<id>`.

## Bewusst nicht genutzt
- **Remotive-API:** Der Suchparameter filtert praktisch nicht, der Feed ist winzig und kaum auf Deutschland bezogen, und die API-Antwort selbst verweist für diesen Zweck auf ein kostenpflichtiges Angebot.
