# Quellen: API-Details und Fallstricke

Diese Datei brauchst du vor jeder Arbeit an `src/jobagent/sources/` oder an den Fixtures in `tests/fixtures/`. Welche Quellen erlaubt sind und warum, steht in ADR 0002.

Jede Quelle ist ein Adapter am Seam `Source` und erfüllt `name` und `search(keywords) -> SearchResult`:
- Sie bekommt alle Suchbegriffe auf einmal.
- Sie dedupliziert intern.
- Sie wirft nie. Fehler meldet sie im `SearchResult` in der Form „<Suchbegriff oder Firma>: <Grund>“.

Der JSON-Abruf mit Fehlergrund und die HTML-zu-Text-Umwandlung liegen einmal in `_http.py`. Die IDs der Anzeigen bleiben stabil, weil die Datenbank an ihnen hängt.

## Bundesagentur für Arbeit (`BundesagenturSource`)
- Doku und Beispiele stehen im GitHub-Projekt `bundesAPI/jobsuche-api`. Endpunkt, Header und Parameter immer dort gegenprüfen.
- Die Live-API (`pc/v6/jobs`) weicht vom dokumentierten Schema ab, zum Beispiel `ergebnisliste` statt `stellenangebote` und `referenznummer` statt `refnr`. Feldnamen gegen echte Antworten verifizieren, nicht nur gegen die Doku.
- Suchparameter:
  - Stichwort (`was`)
  - Ort (`wo`)
  - Umkreis (`umkreis`)
  - Alter der Anzeige (`veroeffentlichtseit`)
- Die Beschreibung kommt per Detail-Call, einmal je Anzeige.
- Die ID ist die rohe `referenznummer`.

## Arbeitnow (`ArbeitnowSource`)
- Freie, öffentliche API ohne Key: `https://www.arbeitnow.com/api/job-board-api`. Sie sammelt Remote- und Europa-Jobs mit Tech-Schwerpunkt.
- Es gibt keine serverseitige Suche nach Stichwort oder Ort. Gefiltert wird lokal, und alle Suchbegriffe teilen sich dieselben abgerufenen Seiten. Ein `umkreis` ist nicht möglich, weil die API keine Geokoordinaten liefert.
- Das Paging folgt `links.next` und stoppt, sobald Einträge älter als `veroeffentlichtseit` Tage auftauchen. Höchstens 10 Seiten pro Lauf, als Sicherheitsgrenze und zur maßvollen Nutzung der freien API.
- Die Uhr kommt über den Konstruktor (`now`).
- Die ID hat die Form `arbeitnow:<slug>`.

## Firmen-Watchlist (`WatchlistSource`)
- Statt einer breiten Suche werden konkrete Firmen aus `config.toml` direkt über ihr öffentliches Jobboard durchsucht:
  - Sie stehen dort als `[[firmen]]` mit `name`, `ats` und `slug`.
  - Im Code heißen sie `WatchlistCompany`.
- Jedes Board wird pro Lauf einmal abgefragt, die Suchbegriffe werden lokal auf den Titel gefiltert.
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
