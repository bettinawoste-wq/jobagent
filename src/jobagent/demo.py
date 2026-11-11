"""Demo-Set fuer den Demo-Lauf: erfundene Anzeigen, vorgefertigte Bewertungen, Demo-Konfiguration.

Alles hier ist synthetisch und oeffentlich: nur erkennbar erfundene Firmen, Links auf
example.com. Die Bewertungen sind so geschrieben, als kaemen sie vom Modell gegen das
Beispiel-Suchprofil `profile.example.md`. Ein Demo-Lauf holt nichts aus dem Netz, fragt
kein Modell und liest oder speichert nichts Persoenliches.
"""

import sqlite3
from collections.abc import Callable
from datetime import date, timedelta

from jobagent import fetch, store
from jobagent.fetch import Anzeige
from jobagent.score import Bewertung
from jobagent.stelle import stellen_schluessel

KONFIG: dict = {
    "was": ["Full-Stack-Entwickler", "IT Consultant", "Embedded Entwickler", "Data Scientist"],
    "mindest_score": 3,
    "nachfassen_ab_tag": 14,
    "nachfassen_bis_tag": 28,
}

_LINK = "https://example.com/stellen/"


def _anzeige(id_: str, titel: str, firma: str, ort: str, beschreibung: str) -> Anzeige:
    return Anzeige(id_, titel, firma, ort, f"{_LINK}{id_}", beschreibung)


# Je Quelle: Suchbegriff -> Anzeigen, die diese Demo-Quelle dafuer "findet".
_BUNDESAGENTUR = {
    "Full-Stack-Entwickler": [
        _anzeige(
            "demo-ba-1",
            "Full-Stack-Entwickler (m/w/d) Python/TypeScript",
            "Fiktiva Software GmbH",
            "Beispielstadt",
            "Wir entwickeln Webanwendungen mit Python, FastAPI und React. Hybrid, 2 Tage Büro.",
        ),
    ],
    "IT Consultant": [
        _anzeige(
            "demo-ba-2",
            "IT Consultant (m/w/d) Prozessdigitalisierung",
            "Exempla Consulting GmbH",
            "Beispielstadt",
            "Beratung von Mittelständlern bei der Digitalisierung, viel Kundenkontakt vor Ort.",
        ),
    ],
    "Embedded Entwickler": [
        _anzeige(
            "demo-ba-3",
            "Embedded-Softwareentwickler C++/Qt (m/w/d)",
            "Platzhalter Systems AG",
            "Musterhausen",
            "Steuerungssoftware für Messgeräte in C++ und Qt, vollständig vor Ort.",
        ),
    ],
}

_ARBEITNOW = {
    "Full-Stack-Entwickler": [
        _anzeige(
            "demo-an-1",
            "Python Developer (w/m/d)",
            "Beispiel Tech",
            "Remote",
            "Backend mit Python und PostgreSQL, Remote in Deutschland, neu: Kubernetes-Erfahrung.",
        ),
    ],
    "Data Scientist": [
        _anzeige(
            "demo-an-2",
            "Data Scientist (m/w/d)",
            "Lorem Data GmbH",
            "Remote",
            "Prognosemodelle mit Python, pandas und scikit-learn, Remote mit Teamtreffen.",
        ),
    ],
    "IT Consultant": [
        _anzeige(
            "demo-an-3",
            "SAP-Berater FI/CO (m/w/d)",
            "Musterfirma Beratung GmbH",
            "Beispielstadt",
            "Einführung von SAP S/4HANA im Finanzwesen, 80 % Reisetätigkeit.",
        ),
    ],
}

_WATCHLIST = {
    "Full-Stack-Entwickler": [
        _anzeige(
            "demo-wl-1",
            "DevOps Engineer (m/w/d)",
            "Testfeld Robotics GmbH",
            "Beispielstadt",
            "CI/CD, Linux und Container für unsere Roboterflotte, Hybrid.",
        ),
    ],
    "Data Scientist": [
        _anzeige(
            "demo-wl-2",
            "Werkstudent Data Analytics (m/w/d)",
            "Testfeld Robotics GmbH",
            "Beispielstadt",
            "Werkstudentenstelle, 20 Stunden pro Woche, Auswertungen mit SQL und Python.",
        ),
    ],
}
_FRUEHERE_ANZEIGE = _anzeige(
    "demo-ba-alt",
    "Python Developer (m/w/d)",
    "Beispiel Tech GmbH",
    "Remote",
    "Backend mit Python und PostgreSQL, Remote in Deutschland.",
)

_WATCHLIST_FEHLER = "Musterwerk AG: Board nicht erreichbar"

BEWERTUNGEN: dict[str, Bewertung] = {
    "demo-ba-1": Bewertung(
        5,
        ["Python und JavaScript/TypeScript", "Full-Stack wie gesucht", "Hybrid in Beispielstadt"],
        [],
        [],
        "Sehr guter Match für die erste Wunschrolle.",
    ),
    "demo-an-1": Bewertung(
        4,
        ["Python, SQL", "Remote"],
        [],
        ["Kubernetes"],
        "Passt gut, Kubernetes wäre neu.",
    ),
    "demo-an-2": Bewertung(
        4,
        ["Data Science mit Python", "Remote"],
        [],
        ["scikit-learn nur in Grundzügen"],
        "Gute Passung zur vierten Wunschrolle.",
    ),
    "demo-ba-2": Bewertung(
        3,
        ["IT Consultant als Wunschrolle", "Anforderungsanalyse"],
        ["Viel Präsenz beim Kunden"],
        [],
        "Rolle passt, Arbeitsmodell nur teilweise.",
    ),
    "demo-ba-3": Bewertung(
        3,
        ["C++ und Qt"],
        ["Vollständig vor Ort", "Musterhausen liegt am Rand des Umkreises"],
        [],
        "Technisch passend, Arbeitsmodell schwächer.",
    ),
    "demo-wl-1": Bewertung(
        3,
        ["Linux, CI/CD", "Hybrid"],
        [],
        ["Container-Orchestrierung"],
        "Solide Alternative in Richtung DevOps.",
    ),
    "demo-wl-2": Bewertung(
        2,
        ["SQL und Python"],
        ["Werkstudentenstelle trotz Berufserfahrung"],
        [],
        "Inhaltlich nah, aber falsches Level.",
    ),
    "demo-an-3": Bewertung(
        1,
        [],
        ["80 % Reisetätigkeit"],
        ["SAP FI/CO"],
        "Fachfremd und kaum vereinbar mit dem Arbeitsmodell.",
    ),
}

Suche = Callable[[str], fetch.Suchergebnis]


def quellen() -> dict[str, Suche]:
    """Drei Demo-Quellen, benannt wie die echten; die Firmen-Watchlist meldet einen Fehler."""
    return {
        "Bundesagentur für Arbeit (Demo)": _suche(_BUNDESAGENTUR),
        "Arbeitnow (Demo)": _suche(_ARBEITNOW),
        "Firmen-Watchlist (Demo)": _suche(_WATCHLIST, [_WATCHLIST_FEHLER]),
    }


def _suche(anzeigen: dict[str, list[Anzeige]], fehler: list[str] | None = None) -> Suche:
    return lambda was: fetch.Suchergebnis(list(anzeigen.get(was, [])), list(fehler or []))


def bewerte(anzeige: Anzeige) -> Bewertung | None:
    """Vorgefertigte Bewertung statt Modellaufruf."""
    return BEWERTUNGEN.get(anzeige.id)


def lege_bewerbungen_an(conn: sqlite3.Connection, heute: date) -> None:
    """Legt die Bewerbungen an, die es vor dem Demo-Lauf schon gibt (Datum relativ zu heute)."""
    # Ohne Antwort und im Nachfass-Fenster: erscheint als Nachfass-Hinweis.
    store.lege_bewerbung_an(
        conn,
        store.NeueBewerbung(
            stellen_schluessel("Datenwerk Muster GmbH", "Data Engineer (m/w/d)"),
            "Datenwerk Muster GmbH",
            "Data Engineer (m/w/d)",
            None,
        ),
        store.BEWORBEN,
        heute - timedelta(days=18),
    )

    # Bewerbung auf eine fruehere Anzeige derselben Stelle: Die neue Anzeige von Arbeitnow
    # (demo-an-1) schreibt Firma und Titel anders und hat einen anderen Text.
    beworben_am = heute - timedelta(days=35)
    store.mark_seen(conn, _FRUEHERE_ANZEIGE, BEWERTUNGEN["demo-an-1"], beworben_am)
    store.lege_bewerbung_an(
        conn,
        store.NeueBewerbung(
            stellen_schluessel(_FRUEHERE_ANZEIGE.firma, _FRUEHERE_ANZEIGE.titel),
            _FRUEHERE_ANZEIGE.firma,
            _FRUEHERE_ANZEIGE.titel,
            _FRUEHERE_ANZEIGE.id,
        ),
        "gespräch",
        beworben_am,
    )
