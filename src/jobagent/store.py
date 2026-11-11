"""SQLite-Speicher: merkt sich gesehene Anzeigen fuer Dedupe und Rueckmeldungen.

Tabellen und Spalten tragen deutsche Namen, damit eine vorhandene jobagent.db ohne
Migration weiter funktioniert. Uebersetzt wird nur hier, in den SQL-Texten.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path

from jobagent.job_ad import JobAd
from jobagent.score import Assessment


class ApplicationStatus(StrEnum):
    """Bewerbungsstatus; die Werte stehen so in der Datenbank und in der Kommandozeile."""

    APPLIED = "beworben"
    INTERVIEW = "gespräch"
    REJECTED = "absage"
    OFFER = "zusage"
    WITHDRAWN = "zurückgezogen"


_SCHEMA_SEEN = """
CREATE TABLE IF NOT EXISTS gesehene_anzeigen (
    id TEXT PRIMARY KEY,
    titel TEXT NOT NULL,
    firma TEXT,
    link TEXT NOT NULL,
    score INTEGER NOT NULL,
    datum TEXT NOT NULL
)
"""

_SCHEMA_APPLICATIONS = """
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
_ADDED_COLUMNS = {
    "report": "TEXT",
    "nummer": "INTEGER",
    "beschreibung_hash": "TEXT",
    "bewertung": "TEXT",
}


@dataclass(frozen=True, slots=True)
class StoredMatch:
    id: str
    title: str
    company: str | None


@dataclass(frozen=True, slots=True)
class NewApplication:
    position_key: str
    company: str | None
    title: str
    job_ad_id: str | None  # None bei manueller Erfassung ohne Treffer


@dataclass(frozen=True, slots=True)
class KnownApplication:
    status: str
    applied_on: date
    description_hash: str | None


@dataclass(frozen=True, slots=True)
class Feedback:
    job_ad_id: str
    title: str
    company: str | None
    model_score: int
    assessment: Assessment | None  # None bei Anzeigen, die vor 0.3.0 gespeichert wurden
    own_score: int
    reason: str | None


@dataclass(frozen=True, slots=True)
class FollowUpReminder:
    company: str | None
    title: str
    applied_on: date


def connect(path: str | Path) -> sqlite3.Connection:
    """Oeffnet (und initialisiert oder migriert bei Bedarf) die SQLite-Datenbank unter path."""
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA_SEEN)
    conn.execute(_SCHEMA_APPLICATIONS)
    conn.execute(_SCHEMA_FEEDBACK)
    _add_missing_columns(conn)
    conn.commit()
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(gesehene_anzeigen)")}
    for name, column_type in _ADDED_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE gesehene_anzeigen ADD COLUMN {name} {column_type}")


def is_new(conn: sqlite3.Connection, job_ad_id: str) -> bool:
    """True, wenn die Anzeigen-ID noch nicht gespeichert ist."""
    row = conn.execute("SELECT 1 FROM gesehene_anzeigen WHERE id = ?", (job_ad_id,)).fetchone()
    return row is None


def mark_seen(
    conn: sqlite3.Connection, job_ad: JobAd, assessment: Assessment, seen_on: date
) -> None:
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
            seen_on.isoformat(),
            description_hash(job_ad.description),
            _assessment_as_json(assessment),
        ),
    )
    conn.commit()


def save_match_numbers(
    conn: sqlite3.Connection, report_name: str, match_numbers: dict[str, int]
) -> None:
    """Haelt fest, unter welcher Treffernummer eine Anzeige in welchem Report steht."""
    conn.executemany(
        "UPDATE gesehene_anzeigen SET report = ?, nummer = ? WHERE id = ?",
        [(report_name, number, job_ad_id) for job_ad_id, number in match_numbers.items()],
    )
    conn.commit()


def find_match(conn: sqlite3.Connection, report_name: str, match_number: int) -> StoredMatch | None:
    """Sucht die Anzeige, die in einem Report unter einer Treffernummer steht."""
    row = conn.execute(
        "SELECT id, titel, firma FROM gesehene_anzeigen WHERE report = ? AND nummer = ?",
        (report_name, match_number),
    ).fetchone()
    return StoredMatch(*row) if row else None


def application_for_job_ad(conn: sqlite3.Connection, job_ad_id: str) -> int | None:
    """Liefert die ID der Bewerbung auf genau diese Anzeige, falls vorhanden."""
    row = conn.execute("SELECT id FROM bewerbungen WHERE anzeige_id = ?", (job_ad_id,)).fetchone()
    return row[0] if row else None


def application_for_position(conn: sqlite3.Connection, position_key: str) -> int | None:
    """Liefert die ID der letzten Bewerbung auf diese Stelle, falls vorhanden."""
    row = conn.execute(
        "SELECT id FROM bewerbungen WHERE stelle = ? ORDER BY beworben_am DESC, id DESC LIMIT 1",
        (position_key,),
    ).fetchone()
    return row[0] if row else None


def create_application(
    conn: sqlite3.Connection, application: NewApplication, status: str, applied_on: date
) -> None:
    conn.execute(
        "INSERT INTO bewerbungen (stelle, firma, titel, anzeige_id, status, beworben_am) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            application.position_key,
            application.company,
            application.title,
            application.job_ad_id,
            status,
            applied_on.isoformat(),
        ),
    )
    conn.commit()


def update_application(
    conn: sqlite3.Connection, application_id: int, status: str, applied_on: date | None
) -> None:
    """Setzt den Status; das Bewerbungsdatum aendert sich nur, wenn eines angegeben ist."""
    conn.execute(
        "UPDATE bewerbungen SET status = ?, beworben_am = COALESCE(?, beworben_am) WHERE id = ?",
        (status, applied_on.isoformat() if applied_on else None, application_id),
    )
    conn.commit()


def delete_application(conn: sqlite3.Connection, application_id: int) -> None:
    conn.execute("DELETE FROM bewerbungen WHERE id = ?", (application_id,))
    conn.commit()


def save_feedback(
    conn: sqlite3.Connection, job_ad_id: str, score: int, reason: str | None, given_on: date
) -> None:
    """Speichert den eigenen Score; neues Feedback ersetzt altes und gilt als unverarbeitet."""
    conn.execute(
        "INSERT OR REPLACE INTO feedback (anzeige_id, score, grund, datum) VALUES (?, ?, ?, ?)",
        (job_ad_id, score, reason, given_on.isoformat()),
    )
    conn.commit()


def latest_application(conn: sqlite3.Connection, position_key: str) -> KnownApplication | None:
    """Liefert die letzte Bewerbung auf diese Stelle; zurueckgezogene zaehlen nicht."""
    row = conn.execute(
        "SELECT b.status, b.beworben_am, g.beschreibung_hash "
        "FROM bewerbungen b LEFT JOIN gesehene_anzeigen g ON g.id = b.anzeige_id "
        "WHERE b.stelle = ? AND b.status != ? "
        "ORDER BY b.beworben_am DESC, b.id DESC LIMIT 1",
        (position_key, ApplicationStatus.WITHDRAWN),
    ).fetchone()
    if row is None:
        return None
    return KnownApplication(row[0], date.fromisoformat(row[1]), row[2])


def follow_up_reminders(
    conn: sqlite3.Connection, today: date, *, min_days: int, max_days: int
) -> list[FollowUpReminder]:
    """Bewerbungen ohne Antwort, deren Datum min_days bis max_days Tage zurueckliegt."""
    rows = conn.execute(
        "SELECT firma, titel, beworben_am FROM bewerbungen "
        "WHERE status = ? AND beworben_am BETWEEN ? AND ? ORDER BY beworben_am, id",
        (
            ApplicationStatus.APPLIED,
            (today - timedelta(days=max_days)).isoformat(),
            (today - timedelta(days=min_days)).isoformat(),
        ),
    ).fetchall()
    return [
        FollowUpReminder(company, title, date.fromisoformat(applied_on))
        for company, title, applied_on in rows
    ]


def open_feedback(conn: sqlite3.Connection) -> list[Feedback]:
    """Liefert alles unverarbeitete Feedback samt Bewertung des Modells."""
    rows = conn.execute(
        "SELECT f.anzeige_id, g.titel, g.firma, g.score, g.bewertung, f.score, f.grund "
        "FROM feedback f JOIN gesehene_anzeigen g ON g.id = f.anzeige_id "
        "WHERE f.verarbeitet = 0 ORDER BY f.datum, f.anzeige_id"
    ).fetchall()
    return [
        Feedback(
            job_ad_id=job_ad_id,
            title=title,
            company=company,
            model_score=model_score,
            assessment=_assessment_from_json(model_score, raw) if raw else None,
            own_score=own_score,
            reason=reason,
        )
        for job_ad_id, title, company, model_score, raw, own_score, reason in rows
    ]


def count_open_feedback(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM feedback WHERE verarbeitet = 0").fetchone()[0]


def mark_feedback_processed(conn: sqlite3.Connection, job_ad_ids: list[str]) -> None:
    conn.executemany(
        "UPDATE feedback SET verarbeitet = 1 WHERE anzeige_id = ?",
        [(job_ad_id,) for job_ad_id in job_ad_ids],
    )
    conn.commit()


def description_hash(description: str | None) -> str | None:
    """Fingerabdruck einer Beschreibung; None, wenn es keinen Text gibt."""
    # Leerraum vereinheitlichen, damit reine Formatierung nicht als
    # Textabweichung zaehlt.
    normalized = " ".join((description or "").split())
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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


def _assessment_from_json(score: int, raw: str) -> Assessment:
    data = json.loads(raw)
    return Assessment(
        score=score,
        fits=data["passt"],
        misfits=data["passt_nicht"],
        gaps=data["luecken"],
        summary=data["kurzfazit"],
    )
