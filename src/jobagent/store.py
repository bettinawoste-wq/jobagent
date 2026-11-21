"""SQLite-Speicher: merkt sich gesehene Anzeigen für Dedupe und Rückmeldungen.

Tabellen und Spalten tragen deutsche Namen, damit eine vorhandene jobagent.db ohne
Migration weiter funktioniert. Übersetzt wird nur hier, in den SQL-Texten.
"""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Self, cast

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

# Seit 0.7.0: Datum und Report-Name jedes vollständigen Laufs (Glossar), für den Suchzeitraum.
_SCHEMA_COMPLETE_RUNS = """
CREATE TABLE IF NOT EXISTS vollstaendige_laeufe (
    datum TEXT NOT NULL,
    report TEXT NOT NULL
)
"""

# Seit 0.3.0. Bestehende Datenbanken bekommen die Spalten beim Öffnen ergänzt,
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
    status: ApplicationStatus
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


class StoreError(Exception):
    """Die Datenbank lässt sich nicht nutzen, z.B. gesperrt oder kaputt.

    Die Meldung ist für die Nutzerin und nennt die Datenbank.
    """


class _Connection:
    """Die SQLite-Verbindung des Store; ihre Betriebsfehler kommen als `StoreError` an."""

    def __init__(self, path: str | Path) -> None:
        self._path = path
        with self._errors():
            self._raw = sqlite3.connect(path)

    @contextmanager
    def _errors(self) -> Iterator[None]:
        try:
            yield
        except sqlite3.DatabaseError as error:
            # Nur Fehler der Datei und des Betriebs (gesperrt, nicht zu öffnen, keine
            # Datenbank). Programmierfehler wie eine geschlossene Verbindung oder eine
            # verletzte Bedingung bleiben, was sie sind.
            if not (
                isinstance(error, sqlite3.OperationalError) or type(error) is sqlite3.DatabaseError
            ):
                raise
            raise StoreError(f"Datenbank {self._path} nicht nutzbar: {error}") from error

    def execute(self, sql: str, parameters: tuple = ()) -> None:
        with self._errors():
            self._raw.execute(sql, parameters)

    # Gelesen wird innerhalb von _errors, denn auch das Lesen der Zeilen kann scheitern.
    def fetchone(self, sql: str, parameters: tuple = ()) -> tuple | None:
        with self._errors():
            return self._raw.execute(sql, parameters).fetchone()

    def fetch_value(self, sql: str, parameters: tuple = ()) -> object:
        """Der Wert einer Abfrage, die genau eine Zeile liefert, etwa mit COUNT oder MAX.

        Kommt doch keine Zeile, ist die Datenbank nicht so, wie der Store sie kennt.
        """
        row = self.fetchone(sql, parameters)
        if row is None:
            raise StoreError(f"Datenbank {self._path} nicht nutzbar: Abfrage ohne Ergebnis")
        return row[0]

    def fetchall(self, sql: str, parameters: tuple = ()) -> list[tuple]:
        with self._errors():
            return self._raw.execute(sql, parameters).fetchall()

    def executemany(self, sql: str, parameters: list[tuple]) -> None:
        with self._errors():
            self._raw.executemany(sql, parameters)

    def commit(self) -> None:
        with self._errors():
            self._raw.commit()

    def rollback(self) -> None:
        with self._errors():
            self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


class Store:
    """Die Datenbank als Context-Manager: hält ihre Verbindung selbst und schließt sie.

    Die Methoden heißen nach den fachlichen Fragen von Lauf, Rückmeldung und
    Profil-Vorschlag, nicht nach SQL. Im Anwendungscode kennt außerhalb dieser Klasse
    niemand SQL oder die Verbindung; nur Tests lesen die Datenbank zur Kontrolle direkt.
    """

    def __init__(self, path: str | Path) -> None:
        """Öffnet (und initialisiert oder migriert bei Bedarf) die Datenbank unter path.

        Lässt sich die Datenbank nicht nutzen, wirft hier und jede Methode `StoreError`.
        """
        self._conn = _Connection(path)
        self._in_transaction = False
        try:
            self._conn.execute(_SCHEMA_SEEN)
            self._conn.execute(_SCHEMA_APPLICATIONS)
            self._conn.execute(_SCHEMA_FEEDBACK)
            self._conn.execute(_SCHEMA_COMPLETE_RUNS)
            self._add_missing_columns()
            self._conn.commit()
        except BaseException:
            self._conn.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Was die Methoden darin speichern, gilt gemeinsam am Ende oder bei Fehler gar nicht.

        Transaktionen lassen sich nicht schachteln. Scheitert auch das Zurücksetzen, ist der
        Store danach geschlossen, damit kein späterer Commit die halbe Transaktion festschreibt.
        """
        if self._in_transaction:
            raise RuntimeError("Transaktionen des Store lassen sich nicht schachteln")
        self._in_transaction = True
        try:
            yield
            self._conn.commit()
        except BaseException:
            # Auch nach gescheitertem Commit zurücksetzen; der erste Fehler bleibt der gemeldete.
            try:
                self._conn.rollback()
            except Exception:  # welcher Fehler auch immer: nichts darf mehr committen
                self._conn.close()
            raise
        finally:
            self._in_transaction = False

    def _commit(self) -> None:
        if not self._in_transaction:
            self._conn.commit()

    def _add_missing_columns(self) -> None:
        existing = {row[1] for row in self._conn.fetchall("PRAGMA table_info(gesehene_anzeigen)")}
        for name, column_type in _ADDED_COLUMNS.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE gesehene_anzeigen ADD COLUMN {name} {column_type}")

    # Gesehene Anzeigen

    def is_new(self, job_ad_id: str) -> bool:
        """True, wenn die Anzeige noch nie gemerkt wurde."""
        row = self._conn.fetchone("SELECT 1 FROM gesehene_anzeigen WHERE id = ?", (job_ad_id,))
        return row is None

    def remember_job_ad(self, job_ad: JobAd, assessment: Assessment, seen_on: date) -> None:
        """Merkt eine Anzeige samt Bewertung und Hash der Beschreibung.

        Der Volltext der Anzeige wird nicht gespeichert.
        """
        self._conn.execute(
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
        self._commit()

    def save_match_numbers(self, report_name: str, match_numbers: dict[str, int]) -> None:
        """Hält fest, unter welcher Treffernummer eine Anzeige in welchem Report steht."""
        self._conn.executemany(
            "UPDATE gesehene_anzeigen SET report = ?, nummer = ? WHERE id = ?",
            [(report_name, number, job_ad_id) for job_ad_id, number in match_numbers.items()],
        )
        self._commit()

    def find_match(self, report_name: str, match_number: int) -> StoredMatch | None:
        """Sucht die Anzeige, die in einem Report unter einer Treffernummer steht."""
        row = self._conn.fetchone(
            "SELECT id, titel, firma FROM gesehene_anzeigen WHERE report = ? AND nummer = ?",
            (report_name, match_number),
        )
        return StoredMatch(*row) if row else None

    # Vollständige Läufe

    def remember_complete_run(self, day: date, report_name: str) -> None:
        """Merkt einen vollständigen Lauf; ab seinem Tag rechnet der nächste Suchzeitraum."""
        self._conn.execute(
            "INSERT INTO vollstaendige_laeufe (datum, report) VALUES (?, ?)",
            (day.isoformat(), report_name),
        )
        self._commit()

    def last_complete_run(self, *, until: date | None = None) -> date | None:
        """Tag des letzten vollständigen Laufs; None, wenn es noch keinen gab.

        Mit `until` zählen nur Läufe bis einschließlich diesem Tag: Ein gemerkter Lauf in
        der Zukunft (etwa nach einer verstellten Uhr) bestimmt dann nicht den Suchzeitraum.
        """
        # Ohne passenden vollständigen Lauf liefert MAX NULL; ISO-Daten sortieren als Text.
        last_day = until.isoformat() if until else None
        day = self._conn.fetch_value(
            "SELECT MAX(datum) FROM vollstaendige_laeufe WHERE ? IS NULL OR datum <= ?",
            (last_day, last_day),
        )
        return date.fromisoformat(cast(str, day)) if day else None

    # Bewerbungen

    def current_application(
        self, position_key: str | None, *, job_ad_id: str | None = None
    ) -> KnownApplication | None:
        """Die letzte nicht zurückgezogene Bewerbung auf diese Stelle (für den Report).

        Mit `job_ad_id` zählt auch eine Bewerbung auf genau diese Anzeige, selbst ohne
        `position_key`, etwa weil die Anzeige keine Firma nennt.
        """
        row = self._conn.fetchone(
            "SELECT b.status, b.beworben_am, g.beschreibung_hash "
            "FROM bewerbungen b LEFT JOIN gesehene_anzeigen g ON g.id = b.anzeige_id "
            "WHERE (b.stelle = ? OR b.anzeige_id = ?) AND b.status != ? "
            "ORDER BY b.beworben_am DESC, b.id DESC LIMIT 1",
            (position_key, job_ad_id, ApplicationStatus.WITHDRAWN),
        )
        if row is None:
            return None
        return KnownApplication(ApplicationStatus(row[0]), date.fromisoformat(row[1]), row[2])

    def latest_application_id(self, position_key: str) -> int | None:
        """ID der letzten Bewerbung auf diese Stelle, auch einer zurückgezogenen.

        Für die Rückmeldung: Eine erneute Bewerbung nach dem Zurückziehen
        überschreibt die alte.
        """
        row = self._conn.fetchone(
            "SELECT id FROM bewerbungen WHERE stelle = ? "
            "ORDER BY beworben_am DESC, id DESC LIMIT 1",
            (position_key,),
        )
        return row[0] if row else None

    def application_for_job_ad(self, job_ad_id: str) -> int | None:
        """ID der Bewerbung auf genau diese Anzeige, falls vorhanden."""
        row = self._conn.fetchone("SELECT id FROM bewerbungen WHERE anzeige_id = ?", (job_ad_id,))
        return row[0] if row else None

    def create_application(
        self, application: NewApplication, status: ApplicationStatus, applied_on: date
    ) -> None:
        self._conn.execute(
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
        self._commit()

    def update_application(
        self, application_id: int, status: ApplicationStatus, applied_on: date | None
    ) -> None:
        """Setzt den Status; das Bewerbungsdatum ändert sich nur, wenn eines angegeben ist."""
        self._conn.execute(
            "UPDATE bewerbungen SET status = ?, beworben_am = COALESCE(?, beworben_am) "
            "WHERE id = ?",
            (status, applied_on.isoformat() if applied_on else None, application_id),
        )
        self._commit()

    def delete_application(self, application_id: int) -> None:
        self._conn.execute("DELETE FROM bewerbungen WHERE id = ?", (application_id,))
        self._commit()

    def follow_up_reminders(
        self, today: date, *, min_days: int, max_days: int
    ) -> list[FollowUpReminder]:
        """Bewerbungen ohne Antwort, deren Datum min_days bis max_days Tage zurückliegt."""
        rows = self._conn.fetchall(
            "SELECT firma, titel, beworben_am FROM bewerbungen "
            "WHERE status = ? AND beworben_am BETWEEN ? AND ? ORDER BY beworben_am, id",
            (
                ApplicationStatus.APPLIED,
                (today - timedelta(days=max_days)).isoformat(),
                (today - timedelta(days=min_days)).isoformat(),
            ),
        )
        return [
            FollowUpReminder(company, title, date.fromisoformat(applied_on))
            for company, title, applied_on in rows
        ]

    # Feedback

    def save_feedback(self, job_ad_id: str, score: int, reason: str | None, given_on: date) -> None:
        """Speichert den eigenen Score; neues Feedback ersetzt altes und gilt als unverarbeitet."""
        self._conn.execute(
            "INSERT OR REPLACE INTO feedback (anzeige_id, score, grund, datum) VALUES (?, ?, ?, ?)",
            (job_ad_id, score, reason, given_on.isoformat()),
        )
        self._commit()

    def open_feedback(self) -> list[Feedback]:
        """Alles Feedback, das in keinen Profil-Vorschlag eingeflossen ist, samt Bewertung."""
        rows = self._conn.fetchall(
            "SELECT f.anzeige_id, g.titel, g.firma, g.score, g.bewertung, f.score, f.grund "
            "FROM feedback f JOIN gesehene_anzeigen g ON g.id = f.anzeige_id "
            "WHERE f.verarbeitet = 0 ORDER BY f.datum, f.anzeige_id"
        )
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

    def count_open_feedback(self) -> int:
        """Wie viel Feedback noch in keinen Profil-Vorschlag eingeflossen ist."""
        count = self._conn.fetch_value("SELECT COUNT(*) FROM feedback WHERE verarbeitet = 0")
        return cast(int, count)

    def mark_feedback_processed(self, job_ad_ids: list[str]) -> None:
        self._conn.executemany(
            "UPDATE feedback SET verarbeitet = 1 WHERE anzeige_id = ?",
            [(job_ad_id,) for job_ad_id in job_ad_ids],
        )
        self._commit()


def description_hash(description: str | None) -> str | None:
    """Fingerabdruck einer Beschreibung; None, wenn es keinen Text gibt."""
    # Leerraum vereinheitlichen, damit reine Formatierung nicht als
    # Textabweichung zählt.
    normalized = " ".join((description or "").split())
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# Die Spalte bewertung nutzt dieselben deutschen Schlüssel wie die Modelle
# (ADR 0005), daher dieselbe Übersetzung aus score.ASSESSMENT_KEYS.
def _assessment_as_json(assessment: Assessment) -> str:
    return json.dumps(assessment.as_model_data(), ensure_ascii=False)


def _assessment_from_json(score: int, raw: str) -> Assessment:
    return Assessment.from_model_data(score, json.loads(raw))
