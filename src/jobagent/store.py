"""SQLite-Speicher: merkt sich gesehene Anzeigen fuer Dedupe und Rueckmeldungen."""

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

from jobagent.fetch import Anzeige
from jobagent.score import Bewertung

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

# Seit 0.3.0. Bestehende Datenbanken bekommen die Spalten beim Oeffnen ergaenzt,
# ihre Zeilen bleiben dort leer.
_ERGAENZTE_SPALTEN = {
    "report": "TEXT",
    "nummer": "INTEGER",
    "beschreibung_hash": "TEXT",
    "bewertung": "TEXT",
}


def connect(pfad: str | Path) -> sqlite3.Connection:
    """Oeffnet (und initialisiert oder migriert bei Bedarf) die SQLite-Datenbank unter pfad."""
    conn = sqlite3.connect(pfad)
    conn.execute(_SCHEMA)
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


def mark_seen(
    conn: sqlite3.Connection, anzeige: Anzeige, bewertung: Bewertung, datum: date
) -> None:
    """Merkt eine Anzeige als gesehen, samt Bewertung und Hash der Beschreibung.

    Der Volltext der Anzeige wird nicht gespeichert.
    """
    conn.execute(
        "INSERT INTO gesehene_anzeigen "
        "(id, titel, firma, link, score, datum, beschreibung_hash, bewertung) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            anzeige.id,
            anzeige.titel,
            anzeige.firma,
            anzeige.link,
            bewertung.score,
            datum.isoformat(),
            _beschreibung_hash(anzeige.beschreibung),
            _bewertung_als_json(bewertung),
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


def _beschreibung_hash(beschreibung: str | None) -> str | None:
    # Leerraum vereinheitlichen, damit reine Formatierung nicht als
    # Textabweichung zaehlt.
    normalisiert = " ".join((beschreibung or "").split())
    if not normalisiert:
        return None
    return hashlib.sha256(normalisiert.encode("utf-8")).hexdigest()


def _bewertung_als_json(bewertung: Bewertung) -> str:
    return json.dumps(
        {
            "passt": bewertung.passt,
            "passt_nicht": bewertung.passt_nicht,
            "luecken": bewertung.luecken,
            "kurzfazit": bewertung.kurzfazit,
        },
        ensure_ascii=False,
    )
