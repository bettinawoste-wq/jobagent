"""SQLite-Speicher: merkt sich gesehene Anzeigen fuer Dedupe."""

import sqlite3
from datetime import date
from pathlib import Path

from jobagent.fetch import Anzeige

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


def connect(pfad: str | Path) -> sqlite3.Connection:
    """Oeffnet (und initialisiert bei Bedarf) die SQLite-Datenbank unter pfad."""
    conn = sqlite3.connect(pfad)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def is_new(conn: sqlite3.Connection, anzeige_id: str) -> bool:
    """True, wenn die Anzeigen-ID noch nicht gespeichert ist."""
    row = conn.execute("SELECT 1 FROM gesehene_anzeigen WHERE id = ?", (anzeige_id,)).fetchone()
    return row is None


def mark_seen(conn: sqlite3.Connection, anzeige: Anzeige, score: int, datum: date) -> None:
    """Merkt eine Anzeige als gesehen (nur id, titel, firma, link, score, datum)."""
    conn.execute(
        "INSERT INTO gesehene_anzeigen (id, titel, firma, link, score, datum) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (anzeige.id, anzeige.titel, anzeige.firma, anzeige.link, score, datum.isoformat()),
    )
    conn.commit()
