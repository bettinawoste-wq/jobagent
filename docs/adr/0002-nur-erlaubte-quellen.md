---
status: accepted
---

# Nur Quellen mit öffentlicher Schnittstelle nutzen

## Kontext

Viele Stellenanzeigen stehen auf großen Plattformen wie LinkedIn, Xing und Indeed. Wer dort mitliest, findet mehr Treffer. Diese Seiten untersagen aber das automatisierte Auslesen. Diese Grenze steht seit dem ersten Commit in `CLAUDE.md`.

## Entscheidung

Der Agent holt Anzeigen nur aus Quellen, die dafür eine öffentliche Schnittstelle anbieten:

- **Bundesagentur für Arbeit**: die Jobsuche-API, dokumentiert im Projekt `bundesAPI/jobsuche-api`.
- **Arbeitnow**: eine freie, öffentliche API ohne Key. Sie wird maßvoll genutzt, mit höchstens 10 Seiten pro Lauf für alle Suchbegriffe zusammen.
- **Firmen-Watchlist**: die öffentlichen Jobboards einzelner Firmen bei Greenhouse und Lever, die man in `config.toml` selbst einträgt.

Für LinkedIn, Xing, Indeed und andere Seiten, die automatisiertes Auslesen untersagen, gibt es keine Scraper.

Maßvoll heißt konkret (seit Version 0.8.0):

- Zwischen zwei Anfragen an die Bundesagentur oder an Arbeitnow liegen mindestens 0,5 s.
- Die Bundesagentur blättert je Suchbegriff höchstens 5 Seiten à 50 Treffer.
- Detail-Abrufe gibt es nur für Anzeigen, die der Agent noch nicht gemerkt hat.

## Verworfene Alternativen

- **Scraper für LinkedIn, Xing oder Indeed.** Mehr Anzeigen, aber gegen die Regeln dieser Seiten. Ausgeschlossen.
- **Remotive-API als dritte Quelle.** Sie war vorgeschlagen und wurde gegen echte Antworten geprüft, dann verworfen, weil
  - ihr Suchparameter praktisch nicht filtert,
  - ihr Angebot sehr klein ist und kaum Anzeigen mit Deutschland-Bezug enthält,
  - die API-Antwort selbst auf ein kostenpflichtiges Angebot für diesen Nutzungszweck hinweist.

  Stattdessen kam die Firmen-Watchlist dazu (Commit `d0b2533`).

## Konsequenzen

- Der Agent sieht nur einen Teil des Markts. Anzeigen, die ausschließlich auf LinkedIn, Xing oder Indeed stehen, findet er nicht.
- Arbeitnow, Greenhouse und Lever bieten keine Stichwortsuche auf dem Server. Der Agent lädt deshalb mehr herunter, als er braucht, und filtert selbst nach den Suchbegriffen.
- Die Watchlist ist Handarbeit: Sie findet nur Firmen, die man kennt und einträgt, dafür direkt an der Quelle.
- Arbeitnow sucht nicht auf dem Server, und 10 Seiten reichen nur für wenige Tage. Das Ende nach 10 Seiten ist deshalb ein Hinweis der Quelle, kein Fehler: Sonst wäre kein Lauf vollständig, und der Suchzeitraum bliebe dauerhaft beim Höchstwert. Bei der Bundesagentur bleibt das Abschneiden ein Fehler, weil es dort selten ist und Anzeigen fehlen.
- Ein Lauf dauert durch die Pausen länger, bei täglichen Läufen etwa eine halbe Minute.
- Die Live-API der Bundesagentur weicht vom dokumentierten Schema ab. Jede Änderung an dieser Quelle muss gegen echte Antworten geprüft werden, nicht nur gegen die Doku.
- Eine neue Quelle kommt nur dazu, wenn sie eine öffentliche Schnittstelle hat, deren Bedingungen die Nutzung für diesen Zweck erlauben.
