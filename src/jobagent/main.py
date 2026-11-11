"""Ablauf: fetch, dedupe, score, report."""

import argparse
import io
import logging
import sqlite3
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path

from jobagent import demo, fetch, report, score, store
from jobagent.job_ad import JobAd
from jobagent.position import position_key

logger = logging.getLogger(__name__)

_KONFIG_PFAD = Path("config.toml")
_PROFIL_PFAD = Path("profile.md")
_DB_PFAD = Path("jobagent.db")
_NACHFASSEN_AB_TAG = 14
_NACHFASSEN_BIS_TAG = 28
_PROFILVORSCHLAG_AB_FEEDBACK = 5

Suche = Callable[[str], fetch.Suchergebnis]
"""Sucht in einer Quelle nach einem Stichwort (`was`)."""

Bewerte = Callable[[JobAd], score.Assessment | None]
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
        bewerte = _haiku_assessment(profil_pfad.read_text(encoding="utf-8"))
    heute = date.today()

    conn = store.connect(db_pfad)
    try:
        job_ads, quellenstatus = _suche_alle(quellen, konfig.get("was", []))
        neue_treffer = _neue_treffer(conn, job_ads, bewerte, heute)
        geschrieben = report.write_report(
            neue_treffer,
            heute,
            ausgabe_verzeichnis,
            sources=quellenstatus,
            min_score=konfig.get("mindest_score", report.DEFAULT_MIN_SCORE),
            applications=_bereits_beworben(conn, neue_treffer),
            follow_ups=store.follow_up_reminders(
                conn,
                heute,
                min_days=konfig.get("nachfassen_ab_tag", _NACHFASSEN_AB_TAG),
                max_days=konfig.get("nachfassen_bis_tag", _NACHFASSEN_BIS_TAG),
            ),
            open_feedback=_offenes_feedback(conn),
        )
        store.save_match_numbers(conn, geschrieben.path.stem, geschrieben.match_numbers)
        return geschrieben.path
    finally:
        conn.close()


def _lade_konfig(pfad: Path) -> dict:
    with pfad.open("rb") as datei:
        return tomllib.load(datei)


def _haiku_assessment(profil: str) -> Bewerte:
    return lambda job_ad: score.score_job_ad(job_ad, profil)


def _neue_treffer(
    conn: sqlite3.Connection,
    job_ads: list[JobAd],
    bewerte: Bewerte,
    heute: date,
) -> list[report.Match]:
    treffer: list[report.Match] = []

    for job_ad in job_ads:
        if not store.is_new(conn, job_ad.id):
            continue

        assessment = bewerte(job_ad)
        if assessment is None:
            logger.warning("Bewertung uebersprungen, bleibt fuer naechsten Lauf (id=%r)", job_ad.id)
            continue

        store.mark_seen(conn, job_ad, assessment, heute)
        treffer.append((job_ad, assessment))

    return treffer


def _offenes_feedback(conn: sqlite3.Connection) -> int:
    anzahl = store.count_open_feedback(conn)
    return anzahl if anzahl >= _PROFILVORSCHLAG_AB_FEEDBACK else 0


def _bereits_beworben(
    conn: sqlite3.Connection, treffer: list[report.Match]
) -> dict[str, report.AlreadyApplied]:
    ergebnis: dict[str, report.AlreadyApplied] = {}
    for job_ad, _ in treffer:
        if not job_ad.company:  # Nur der Titel reicht nicht, um eine Stelle zu erkennen.
            continue
        bewerbung = store.latest_application(conn, position_key(job_ad.company, job_ad.title))
        if bewerbung is not None:
            ergebnis[job_ad.id] = report.AlreadyApplied(
                bewerbung.status,
                bewerbung.applied_on,
                _text_differs(
                    store.description_hash(job_ad.description), bewerbung.description_hash
                ),
            )
    return ergebnis


def _text_differs(neu: str | None, bei_bewerbung: str | None) -> str:
    if neu is None or bei_bewerbung is None:
        return "Text nicht vergleichbar"
    return "Text identisch" if neu == bei_bewerbung else "Text weicht von deiner Bewerbung ab"


def _suche_alle(
    quellen: Mapping[str, Suche], suchbegriffe: list[str]
) -> tuple[list[JobAd], list[fetch.Quellenstatus]]:
    gefunden: dict[str, JobAd] = {}
    status: list[fetch.Quellenstatus] = []

    for name, suche in quellen.items():
        ids: set[str] = set()
        fehler: dict[str, None] = {}  # dict statt set: Reihenfolge bleibt erhalten
        for was in suchbegriffe:
            ergebnis = _sichere_suche(suche, was, name)
            fehler.update(dict.fromkeys(ergebnis.fehler))
            for job_ad in ergebnis.job_ads:
                ids.add(job_ad.id)
                gefunden.setdefault(job_ad.id, job_ad)
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


def cli(argumente: list[str] | None = None) -> None:
    """Kommandozeile: ein echter Lauf oder mit `--demo` ein Demo-Lauf."""
    parser = argparse.ArgumentParser(prog="python -m jobagent.main")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Demo-Lauf: erfundene Anzeigen und vorgefertigte Bewertungen, ohne API-Key und "
        "ohne Netz; der Report erscheint auf stdout",
    )
    parser.add_argument(
        "--ausgabe",
        type=Path,
        metavar="ORDNER",
        help="nur mit --demo: Report zusätzlich als Datei in ORDNER schreiben",
    )
    args = parser.parse_args(argumente)
    if args.ausgabe is not None and not args.demo:
        parser.error("--ausgabe gibt es nur zusammen mit --demo")

    if args.demo:
        _schreibe_utf8(demo_lauf(args.ausgabe))
    else:
        main()


def demo_lauf(ausgabe: Path | None = None) -> str:
    """Fuehrt einen Demo-Lauf aus und liefert den Report-Text.

    Datenbank und Report liegen in einem temporaeren Ordner, der danach verschwindet;
    nur mit `ausgabe` bleibt der Report zusaetzlich dort als Datei liegen.
    """
    with tempfile.TemporaryDirectory(prefix="jobagent-demo-") as temp:
        db_pfad = Path(temp) / "demo.db"
        conn = store.connect(db_pfad)
        try:
            demo.lege_bewerbungen_an(conn, date.today())
        finally:
            conn.close()
        pfad = main(
            db_pfad=db_pfad,
            ausgabe_verzeichnis=ausgabe or Path(temp),
            konfig=demo.KONFIG,
            quellen=demo.quellen(),
            bewerte=demo.bewerte,
        )
        return pfad.read_text(encoding="utf-8")


def _schreibe_utf8(text: str) -> None:
    # Die Windows-Konsole nutzt sonst eine Codepage, in der Umlaute kaputtgehen.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    cli()
