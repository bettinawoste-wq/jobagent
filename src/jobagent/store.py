"""SQLite-Speicher: merkt sich gesehene Anzeigen fuer Dedupe und Rueckmeldungen."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from jobagent.job_ad import JobAd
from jobagent.score import Assessment

BEWORBEN = "beworben"
ZURUECKGEZOGEN = "zurückgezogen"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gesehene_anzeigen (
    id TEXT PRIMARY KEY,
    titel TEXT NOT NULL,
    firma TEXT,
    link TEXT NOT NULL,
    score INTEGER NOT NULL,
    datum TEXT NOT NULL
)
"""

_SCHEMA_BEWERBUNGEN = """
CREATE TABLE IF NOT EXISTS bewerbungen (
    id INTEGER PRIMARY KEY,
    stelle TEXT NOT NULL,
    firma TEXT,
    titel TEXT NOT NULL,
    anzeige_id TEXT UNIQUE,
    status TEXT NOT NULL,
    beworben_am TEXT NOT NULL
)
"""

_SCHEMA_FEEDBACK = """
CREATE TABLE IF NOT EXISTS feedback (
    anzeige_id TEXT PRIMARY KEY,
    score INTEGER NOT NULL,
    grund TEXT,
    datum TEXT NOT NULL,
    verarbeitet INTEGER NOT NULL DEFAULT 0
)
"""

# Seit 0.3.0. Bestehende Datenbanken bekommen die Spalten beim Oeffnen ergaenzt,
# ihre Zeilen bleiben dort leer.
_ERGAENZTE_SPALTEN = {
    "report": "TEXT",
    "nummer": "INTEGER",
    "beschreibung_hash": "TEXT",
    "bewertung": "TEXT",
}


@dataclass(frozen=True, slots=True)
class GespeicherterTreffer:
    id: str
    titel: str
    firma: str | None


@dataclass(frozen=True, slots=True)
class NeueBewerbung:
    stelle: str
    firma: str | None
    titel: str
    anzeige_id: str | None  # None bei manueller Erfassung ohne Treffer


@dataclass(frozen=True, slots=True)
class BekannteBewerbung:
    status: str
    beworben_am: date
    beschreibung_hash: str | None


@dataclass(frozen=True, slots=True)
class Rueckmeldung:
    anzeige_id: str
    titel: str
    firma: str | None
    modell_score: int
    bewertung: dict
    eigener_score: int
    grund: str | None


@dataclass(frozen=True, slots=True)
class Nachfasskandidat:
    firma: str | None
    titel: str
    beworben_am: date


def connect(pfad: str | Path) -> sqlite3.Connection:
    """Oeffnet (und initialisiert oder migriert bei Bedarf) die SQLite-Datenbank unter pfad."""
    conn = sqlite3.connect(pfad)
    conn.execute(_SCHEMA)
    conn.execute(_SCHEMA_BEWERBUNGEN)
    conn.execute(_SCHEMA_FEEDBACK)
    _ergaenze_fehlende_spalten(conn)
    conn.commit()
    return conn


def _ergaenze_fehlende_spalten(conn: sqlite3.Connection) -> None:
    vorhanden = {zeile[1] for zeile in conn.execute("PRAGMA table_info(gesehene_anzeigen)")}
    for name, typ in _ERGAENZTE_SPALTEN.items():
        if name not in vorhanden:
            conn.execute(f"ALTER TABLE gesehene_anzeigen ADD COLUMN {name} {typ}")


def is_new(conn: sqlite3.Connection, anzeige_id: str) -> bool:
    """True, wenn die Anzeigen-ID noch nicht gespeichert ist."""
    row = conn.execute("SELECT 1 FROM gesehene_anzeigen WHERE id = ?", (anzeige_id,)).fetchone()
    return row is None


def mark_seen(conn: sqlite3.Connection, job_ad: JobAd, assessment: Assessment, datum: date) -> None:
    """Merkt eine Anzeige als gesehen, samt Bewertung und Hash der Beschreibung.

    Der Volltext der Anzeige wird nicht gespeichert.
    """
    conn.execute(
        "INSERT INTO gesehene_anzeigen "
        "(id, titel, firma, link, score, datum, beschreibung_hash, bewertung) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            job_ad.id,
            job_ad.title,
            job_ad.company,
            job_ad.link,
            assessment.score,
            datum.isoformat(),
            beschreibung_hash(job_ad.description),
            _assessment_as_json(assessment),
        ),
    )
    conn.commit()


def merke_treffernummern(
    conn: sqlite3.Connection, report_name: str, nummern: dict[str, int]
) -> None:
    """Haelt fest, unter welcher Treffernummer eine Anzeige in welchem Report steht."""
    conn.executemany(
        "UPDATE gesehene_anzeigen SET report = ?, nummer = ? WHERE id = ?",
        [(report_name, nummer, anzeige_id) for anzeige_id, nummer in nummern.items()],
    )
    conn.commit()


def finde_treffer(
    conn: sqlite3.Connection, report_name: str, nummer: int
) -> GespeicherterTreffer | None:
    """Sucht die Anzeige, die in einem Report unter einer Treffernummer steht."""
    zeile = conn.execute(
        "SELECT id, titel, firma FROM gesehene_anzeigen WHERE report = ? AND nummer = ?",
        (report_name, nummer),
    ).fetchone()
    return GespeicherterTreffer(*zeile) if zeile else None


def bewerbung_zu_anzeige(conn: sqlite3.Connection, anzeige_id: str) -> int | None:
    """Liefert die ID der Bewerbung auf genau diese Anzeige, falls vorhanden."""
    zeile = conn.execute(
        "SELECT id FROM bewerbungen WHERE anzeige_id = ?", (anzeige_id,)
    ).fetchone()
    return zeile[0] if zeile else None


def bewerbung_zu_stelle(conn: sqlite3.Connection, stelle: str) -> int | None:
    """Liefert die ID der letzten Bewerbung auf diese Stelle, falls vorhanden."""
    zeile = conn.execute(
        "SELECT id FROM bewerbungen WHERE stelle = ? ORDER BY beworben_am DESC, id DESC LIMIT 1",
        (stelle,),
    ).fetchone()
    return zeile[0] if zeile else None


def lege_bewerbung_an(
    conn: sqlite3.Connection, bewerbung: NeueBewerbung, status: str, beworben_am: date
) -> None:
    conn.execute(
        "INSERT INTO bewerbungen (stelle, firma, titel, anzeige_id, status, beworben_am) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            bewerbung.stelle,
            bewerbung.firma,
            bewerbung.titel,
            bewerbung.anzeige_id,
            status,
            beworben_am.isoformat(),
        ),
    )
    conn.commit()


def aktualisiere_bewerbung(
    conn: sqlite3.Connection, bewerbung_id: int, status: str, beworben_am: date | None
) -> None:
    """Setzt den Status; das Bewerbungsdatum aendert sich nur, wenn eines angegeben ist."""
    conn.execute(
        "UPDATE bewerbungen SET status = ?, beworben_am = COALESCE(?, beworben_am) WHERE id = ?",
        (status, beworben_am.isoformat() if beworben_am else None, bewerbung_id),
    )
    conn.commit()


def loesche_bewerbung(conn: sqlite3.Connection, bewerbung_id: int) -> None:
    conn.execute("DELETE FROM bewerbungen WHERE id = ?", (bewerbung_id,))
    conn.commit()


def speichere_feedback(
    conn: sqlite3.Connection, anzeige_id: str, score: int, grund: str | None, datum: date
) -> None:
    """Speichert den eigenen Score; neues Feedback ersetzt altes und gilt als unverarbeitet."""
    conn.execute(
        "INSERT OR REPLACE INTO feedback (anzeige_id, score, grund, datum) VALUES (?, ?, ?, ?)",
        (anzeige_id, score, grund, datum.isoformat()),
    )
    conn.commit()


def letzte_bewerbung(conn: sqlite3.Connection, stelle: str) -> BekannteBewerbung | None:
    """Liefert die letzte Bewerbung auf diese Stelle; zurueckgezogene zaehlen nicht."""
    zeile = conn.execute(
        "SELECT b.status, b.beworben_am, g.beschreibung_hash "
        "FROM bewerbungen b LEFT JOIN gesehene_anzeigen g ON g.id = b.anzeige_id "
        "WHERE b.stelle = ? AND b.status != ? "
        "ORDER BY b.beworben_am DESC, b.id DESC LIMIT 1",
        (stelle, ZURUECKGEZOGEN),
    ).fetchone()
    if zeile is None:
        return None
    return BekannteBewerbung(zeile[0], date.fromisoformat(zeile[1]), zeile[2])


def zum_nachfassen(
    conn: sqlite3.Connection, heute: date, *, ab_tag: int, bis_tag: int
) -> list[Nachfasskandidat]:
    """Bewerbungen ohne Antwort, deren Datum ab_tag bis bis_tag Tage zurueckliegt."""
    zeilen = conn.execute(
        "SELECT firma, titel, beworben_am FROM bewerbungen "
        "WHERE status = ? AND beworben_am BETWEEN ? AND ? ORDER BY beworben_am, id",
        (
            BEWORBEN,
            (heute - timedelta(days=bis_tag)).isoformat(),
            (heute - timedelta(days=ab_tag)).isoformat(),
        ),
    ).fetchall()
    return [Nachfasskandidat(firma, titel, date.fromisoformat(am)) for firma, titel, am in zeilen]


def offene_rueckmeldungen(conn: sqlite3.Connection) -> list[Rueckmeldung]:
    """Liefert alles unverarbeitete Feedback samt Bewertung des Modells."""
    zeilen = conn.execute(
        "SELECT f.anzeige_id, g.titel, g.firma, g.score, g.bewertung, f.score, f.grund "
        "FROM feedback f JOIN gesehene_anzeigen g ON g.id = f.anzeige_id "
        "WHERE f.verarbeitet = 0 ORDER BY f.datum, f.anzeige_id"
    ).fetchall()
    return [
        Rueckmeldung(
            anzeige_id=anzeige_id,
            titel=titel,
            firma=firma,
            modell_score=modell_score,
            bewertung=json.loads(bewertung) if bewertung else {},
            eigener_score=eigener_score,
            grund=grund,
        )
        for anzeige_id, titel, firma, modell_score, bewertung, eigener_score, grund in zeilen
    ]


def anzahl_offenes_feedback(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM feedback WHERE verarbeitet = 0").fetchone()[0]


def markiere_feedback_verarbeitet(conn: sqlite3.Connection, anzeige_ids: list[str]) -> None:
    conn.executemany(
        "UPDATE feedback SET verarbeitet = 1 WHERE anzeige_id = ?",
        [(anzeige_id,) for anzeige_id in anzeige_ids],
    )
    conn.commit()


def beschreibung_hash(beschreibung: str | None) -> str | None:
    """Fingerabdruck einer Beschreibung; None, wenn es keinen Text gibt."""
    # Leerraum vereinheitlichen, damit reine Formatierung nicht als
    # Textabweichung zaehlt.
    normalisiert = " ".join((beschreibung or "").split())
    if not normalisiert:
        return None
    return hashlib.sha256(normalisiert.encode("utf-8")).hexdigest()


def _assessment_as_json(assessment: Assessment) -> str:
    return json.dumps(
        {
            "passt": assessment.fits,
            "passt_nicht": assessment.misfits,
            "luecken": assessment.gaps,
            "kurzfazit": assessment.summary,
        },
        ensure_ascii=False,
    )
