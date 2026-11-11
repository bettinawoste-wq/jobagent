"""Ablauf: fetch, dedupe, score, report."""

import logging
import sqlite3
import tomllib
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path

from jobagent import fetch, report, score, store
from jobagent.stelle import stellen_schluessel

logger = logging.getLogger(__name__)

_KONFIG_PFAD = Path("config.toml")
_PROFIL_PFAD = Path("profile.md")
_DB_PFAD = Path("jobagent.db")
_NACHFASSEN_AB_TAG = 14
_NACHFASSEN_BIS_TAG = 28
_PROFILVORSCHLAG_AB_FEEDBACK = 5

Suche = Callable[[str], fetch.Suchergebnis]
"""Sucht in einer Quelle nach einem Stichwort (`was`)."""

Bewerte = Callable[[fetch.Anzeige], score.Bewertung | None]
"""Bewertet eine Anzeige; None heisst: diesmal nicht bewertbar, naechster Lauf versucht es neu."""


def main(
    *,
    konfig_pfad: Path = _KONFIG_PFAD,
    profil_pfad: Path = _PROFIL_PFAD,
    db_pfad: Path = _DB_PFAD,
    ausgabe_verzeichnis: Path = report.OUTPUT_DIR,
    konfig: dict | None = None,
    quellen: Mapping[str, Suche] | None = None,
    bewerte: Bewerte | None = None,
) -> Path:
    """Fuehrt einen Lauf aus: suchen, deduplizieren, bewerten, Report schreiben.

    Ohne `konfig`, `quellen` und `bewerte` gilt `config.toml`, die eingebauten Quellen
    und die Haiku-Bewertung gegen `profile.md`. Wer sie angibt, ersetzt sie: Dann wird
    die jeweilige Datei nicht gelesen und das jeweilige Netz bzw. Modell nicht gefragt.
    """
    logging.basicConfig(level=logging.INFO)

    if konfig is None:
        konfig = _lade_konfig(konfig_pfad)
    if quellen is None:
        quellen = _quellen(konfig)
    if bewerte is None:
        bewerte = _haiku_bewertung(profil_pfad.read_text(encoding="utf-8"))
    heute = date.today()

    conn = store.connect(db_pfad)
    try:
        anzeigen, quellenstatus = _suche_alle(quellen, konfig.get("was", []))
        neue_treffer = _neue_treffer(conn, anzeigen, bewerte, heute)
        geschrieben = report.schreibe_report(
            neue_treffer,
            heute,
            ausgabe_verzeichnis,
            quellen=quellenstatus,
            mindest_score=konfig.get("mindest_score", report.STANDARD_MINDEST_SCORE),
            bewerbungen=_bereits_beworben(conn, neue_treffer),
            nachfassen=store.zum_nachfassen(
                conn,
                heute,
                ab_tag=konfig.get("nachfassen_ab_tag", _NACHFASSEN_AB_TAG),
                bis_tag=konfig.get("nachfassen_bis_tag", _NACHFASSEN_BIS_TAG),
            ),
            offenes_feedback=_offenes_feedback(conn),
        )
        store.merke_treffernummern(conn, geschrieben.pfad.stem, geschrieben.nummern)
        return geschrieben.pfad
    finally:
        conn.close()


def _lade_konfig(pfad: Path) -> dict:
    with pfad.open("rb") as datei:
        return tomllib.load(datei)


def _haiku_bewertung(profil: str) -> Bewerte:
    return lambda anzeige: score.score_anzeige(anzeige, profil)


def _neue_treffer(
    conn: sqlite3.Connection,
    anzeigen: list[fetch.Anzeige],
    bewerte: Bewerte,
    heute: date,
) -> list[report.Treffer]:
    treffer: list[report.Treffer] = []

    for anzeige in anzeigen:
        if not store.is_new(conn, anzeige.id):
            continue

        bewertung = bewerte(anzeige)
        if bewertung is None:
            logger.warning(
                "Bewertung uebersprungen, bleibt fuer naechsten Lauf (id=%r)", anzeige.id
            )
            continue

        store.mark_seen(conn, anzeige, bewertung, heute)
        treffer.append((anzeige, bewertung))

    return treffer


def _offenes_feedback(conn: sqlite3.Connection) -> int:
    anzahl = store.anzahl_offenes_feedback(conn)
    return anzahl if anzahl >= _PROFILVORSCHLAG_AB_FEEDBACK else 0


def _bereits_beworben(
    conn: sqlite3.Connection, treffer: list[report.Treffer]
) -> dict[str, report.BereitsBeworben]:
    ergebnis: dict[str, report.BereitsBeworben] = {}
    for anzeige, _ in treffer:
        if not anzeige.firma:  # Nur der Titel reicht nicht, um eine Stelle zu erkennen.
            continue
        bewerbung = store.letzte_bewerbung(conn, stellen_schluessel(anzeige.firma, anzeige.titel))
        if bewerbung is not None:
            ergebnis[anzeige.id] = report.BereitsBeworben(
                bewerbung.status,
                bewerbung.beworben_am,
                _textvergleich(
                    store.beschreibung_hash(anzeige.beschreibung), bewerbung.beschreibung_hash
                ),
            )
    return ergebnis


def _textvergleich(neu: str | None, bei_bewerbung: str | None) -> str:
    if neu is None or bei_bewerbung is None:
        return "Text nicht vergleichbar"
    return "Text identisch" if neu == bei_bewerbung else "Text weicht von deiner Bewerbung ab"


def _suche_alle(
    quellen: Mapping[str, Suche], suchbegriffe: list[str]
) -> tuple[list[fetch.Anzeige], list[fetch.Quellenstatus]]:
    gefunden: dict[str, fetch.Anzeige] = {}
    status: list[fetch.Quellenstatus] = []

    for name, suche in quellen.items():
        ids: set[str] = set()
        fehler: dict[str, None] = {}  # dict statt set: Reihenfolge bleibt erhalten
        for was in suchbegriffe:
            ergebnis = _sichere_suche(suche, was, name)
            fehler.update(dict.fromkeys(ergebnis.fehler))
            for anzeige in ergebnis.anzeigen:
                ids.add(anzeige.id)
                gefunden.setdefault(anzeige.id, anzeige)
        status.append(fetch.Quellenstatus(name, len(ids), list(fehler)))

    return list(gefunden.values()), status


def _quellen(konfig: dict) -> dict[str, Suche]:
    wo = konfig.get("wo")
    umkreis = konfig.get("umkreis")
    seit = konfig.get("veroeffentlichtseit")
    firmen = konfig.get("firmen", [])

    quellen: dict[str, Suche] = {
        "Bundesagentur für Arbeit": lambda was: fetch.search(
            was, wo=wo, umkreis=umkreis, veroeffentlichtseit=seit
        ),
        "Arbeitnow": lambda was: fetch.search_arbeitnow(was, wo=wo, veroeffentlichtseit=seit),
    }
    if firmen:
        quellen["Firmen-Watchlist"] = lambda was: fetch.search_watchlist(firmen, was)
    return quellen


def _sichere_suche(suche: Suche, was: str, quelle: str) -> fetch.Suchergebnis:
    # Bekannte Netzwerk- und API-Fehler behandelt fetch selbst. Dieses Netz faengt
    # z.B. ein geaendertes Antwortformat ab: Eine Quelle darf den Lauf nie abbrechen.
    try:
        return suche(was)
    except Exception:
        logger.exception("Unerwarteter Fehler in Quelle %r (was=%r)", quelle, was)
        return fetch.Suchergebnis([], [f"{was}: unerwarteter Fehler"])


if __name__ == "__main__":
    main()
