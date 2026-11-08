"""Ablauf: fetch, dedupe, score, report."""

import logging
import sqlite3
import tomllib
from collections.abc import Callable
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
        anzeigen, quellen = _suche_alle(konfig)
        neue_treffer = _neue_treffer(conn, anzeigen, profil, heute)
        geschrieben = report.schreibe_report(
            neue_treffer,
            heute,
            ausgabe_verzeichnis,
            quellen=quellen,
            mindest_score=konfig.get("mindest_score", report.STANDARD_MINDEST_SCORE),
        )
        store.merke_treffernummern(conn, geschrieben.pfad.stem, geschrieben.nummern)
        return geschrieben.pfad
    finally:
        conn.close()


def _lade_konfig(pfad: Path) -> dict:
    with pfad.open("rb") as datei:
        return tomllib.load(datei)


def _neue_treffer(
    conn: sqlite3.Connection,
    anzeigen: list[fetch.Anzeige],
    profil: str,
    heute: date,
) -> list[report.Treffer]:
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

        store.mark_seen(conn, anzeige, bewertung, heute)
        treffer.append((anzeige, bewertung))

    return treffer


def _suche_alle(konfig: dict) -> tuple[list[fetch.Anzeige], list[fetch.Quellenstatus]]:
    gefunden: dict[str, fetch.Anzeige] = {}
    status: list[fetch.Quellenstatus] = []

    for name, suche in _quellen(konfig).items():
        ids: set[str] = set()
        fehler: dict[str, None] = {}  # dict statt set: Reihenfolge bleibt erhalten
        for was in konfig.get("was", []):
            ergebnis = _sichere_suche(suche, was, name)
            fehler.update(dict.fromkeys(ergebnis.fehler))
            for anzeige in ergebnis.anzeigen:
                ids.add(anzeige.id)
                gefunden.setdefault(anzeige.id, anzeige)
        status.append(fetch.Quellenstatus(name, len(ids), list(fehler)))

    return list(gefunden.values()), status


def _quellen(konfig: dict) -> dict[str, Callable[[str], fetch.Suchergebnis]]:
    wo = konfig.get("wo")
    umkreis = konfig.get("umkreis")
    seit = konfig.get("veroeffentlichtseit")
    firmen = konfig.get("firmen", [])

    quellen: dict[str, Callable[[str], fetch.Suchergebnis]] = {
        "Bundesagentur für Arbeit": lambda was: fetch.search(
            was, wo=wo, umkreis=umkreis, veroeffentlichtseit=seit
        ),
        "Arbeitnow": lambda was: fetch.search_arbeitnow(was, wo=wo, veroeffentlichtseit=seit),
    }
    if firmen:
        quellen["Firmen-Watchlist"] = lambda was: fetch.search_watchlist(firmen, was)
    return quellen


def _sichere_suche(
    suche: Callable[[str], fetch.Suchergebnis], was: str, quelle: str
) -> fetch.Suchergebnis:
    # Bekannte Netzwerk- und API-Fehler behandelt fetch selbst. Dieses Netz faengt
    # z.B. ein geaendertes Antwortformat ab: Eine Quelle darf den Lauf nie abbrechen.
    try:
        return suche(was)
    except Exception:
        logger.exception("Unerwarteter Fehler in Quelle %r (was=%r)", quelle, was)
        return fetch.Suchergebnis([], [f"{was}: unerwarteter Fehler"])


if __name__ == "__main__":
    main()
