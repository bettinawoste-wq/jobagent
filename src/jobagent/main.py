"""Ablauf: fetch, dedupe, score, report."""

import logging
import sqlite3
import tomllib
from datetime import date
from pathlib import Path

from jobagent import fetch, report, score, store

logger = logging.getLogger(__name__)

_KONFIG_PFAD = Path("config.toml")
_PROFIL_PFAD = Path("profile.md")
_DB_PFAD = Path("jobagent.db")


def main(
    *,
    konfig_pfad: Path = _KONFIG_PFAD,
    profil_pfad: Path = _PROFIL_PFAD,
    db_pfad: Path = _DB_PFAD,
    ausgabe_verzeichnis: Path = report.OUTPUT_DIR,
) -> Path:
    """Fuehrt einen Durchgang aus: suchen, deduplizieren, bewerten, Report schreiben."""
    logging.basicConfig(level=logging.INFO)

    konfig = _lade_konfig(konfig_pfad)
    profil = profil_pfad.read_text(encoding="utf-8")
    heute = date.today()

    conn = store.connect(db_pfad)
    try:
        neue_treffer = _neue_treffer(conn, konfig, profil, heute)
        return report.schreibe_report(neue_treffer, heute, ausgabe_verzeichnis)
    finally:
        conn.close()


def _lade_konfig(pfad: Path) -> dict:
    with pfad.open("rb") as datei:
        return tomllib.load(datei)


def _neue_treffer(
    conn: sqlite3.Connection,
    konfig: dict,
    profil: str,
    heute: date,
) -> list[report.Treffer]:
    anzeigen = _suche_alle(konfig)
    treffer: list[report.Treffer] = []

    for anzeige in anzeigen:
        if not store.is_new(conn, anzeige.id):
            continue

        bewertung = score.score_anzeige(anzeige, profil)
        if bewertung is None:
            logger.warning(
                "Bewertung uebersprungen, bleibt fuer naechsten Lauf (id=%r)", anzeige.id
            )
            continue

        store.mark_seen(conn, anzeige, bewertung.score, heute)
        treffer.append((anzeige, bewertung))

    return treffer


def _suche_alle(konfig: dict) -> list[fetch.Anzeige]:
    wo = konfig.get("wo")
    umkreis = konfig.get("umkreis")
    veroeffentlichtseit = konfig.get("veroeffentlichtseit")

    gefunden: dict[str, fetch.Anzeige] = {}
    for was in konfig.get("was", []):
        for anzeige in fetch.search(
            was, wo=wo, umkreis=umkreis, veroeffentlichtseit=veroeffentlichtseit
        ):
            gefunden.setdefault(anzeige.id, anzeige)

    return list(gefunden.values())


if __name__ == "__main__":
    main()
