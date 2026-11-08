"""Kommando fuer Rueckmeldungen: Bewerbungen, Bewerbungsstatus und eigener Score."""

import argparse
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

from jobagent import store
from jobagent.stelle import stellen_schluessel

_DB_PFAD = Path("jobagent.db")

_STATUS = ["beworben", "gespräch", "absage", "zusage", store.ZURUECKGEZOGEN]
_ZURUECKNEHMEN = "zurücknehmen"
_SCORE = "score"

_REPORT_NAME = re.compile(r"\d{4}-\d{2}-\d{2}")

_AUFRUF = """python -m jobagent.feedback REPORT NUMMER AKTION
       python -m jobagent.feedback REPORT NUMMER score 1-5 [GRUND]
       python -m jobagent.feedback AKTION --firma FIRMA --titel TITEL

AKTION: beworben, gespräch, absage, zusage, zurückgezogen, zurücknehmen
Beispiele:
  python -m jobagent.feedback 2026-11-06 3 beworben --am 2026-11-01
  python -m jobagent.feedback 2026-11-06 2 score 4 "Dienstleister ist okay"
  python -m jobagent.feedback absage --firma "Firma X" --titel "Data Engineer\""""


class FeedbackFehler(Exception):
    """Ein Aufruf, der sich nicht ausfuehren laesst; die Meldung ist fuer die Nutzerin."""


def main(
    argv: list[str] | None = None,
    *,
    db_pfad: Path = _DB_PFAD,
    heute: date | None = None,
) -> int:
    """Fuehrt eine Rueckmeldung aus und gibt den Exit-Code zurueck."""
    argumente = sys.argv[1:] if argv is None else argv
    tag = heute or date.today()

    if argumente and _REPORT_NAME.match(argumente[0]):
        parsed = _treffer_parser().parse_args(argumente)
        ausfuehren = _treffer_kommando
    else:
        parsed = _manueller_parser().parse_args(argumente)
        ausfuehren = _manuelles_kommando

    conn = store.connect(db_pfad)
    try:
        print(ausfuehren(conn, parsed, tag))
        return 0
    except FeedbackFehler as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def _treffer_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(usage=_AUFRUF)
    parser.add_argument("report")
    parser.add_argument("nummer", type=int)
    parser.add_argument("aktion", choices=[*_STATUS, _ZURUECKNEHMEN, _SCORE])
    parser.add_argument("werte", nargs="*")
    parser.add_argument("--am")
    return parser


def _manueller_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(usage=_AUFRUF)
    parser.add_argument("aktion", choices=[*_STATUS, _ZURUECKNEHMEN])
    parser.add_argument("--firma", required=True)
    parser.add_argument("--titel", required=True)
    parser.add_argument("--am")
    return parser


def _treffer_kommando(conn: sqlite3.Connection, args: argparse.Namespace, heute: date) -> str:
    report_name = args.report.removesuffix(".md")
    treffer = store.finde_treffer(conn, report_name, args.nummer)
    if treffer is None:
        raise FeedbackFehler(
            f"Treffer {args.nummer} in Report {report_name} nicht gefunden. Reports vor "
            "Version 0.3.0 haben keine Nummern; erfasse die Bewerbung dann mit --firma und --titel."
        )

    if args.aktion == _SCORE:
        return _speichere_score(conn, treffer, args.werte, heute)

    if args.werte:
        raise FeedbackFehler(f"Unerwartete Angaben nach {args.aktion}: {' '.join(args.werte)}")

    bewerbung = store.NeueBewerbung(
        stelle=stellen_schluessel(treffer.firma, treffer.titel),
        firma=treffer.firma,
        titel=treffer.titel,
        anzeige_id=treffer.id,
    )
    bewerbung_id = store.bewerbung_zu_anzeige(conn, treffer.id)
    return _aendere_bewerbung(conn, bewerbung_id, bewerbung, args, heute)


def _manuelles_kommando(conn: sqlite3.Connection, args: argparse.Namespace, heute: date) -> str:
    bewerbung = store.NeueBewerbung(
        stelle=stellen_schluessel(args.firma, args.titel),
        firma=args.firma,
        titel=args.titel,
        anzeige_id=None,
    )
    bewerbung_id = store.bewerbung_zu_stelle(conn, bewerbung.stelle)
    return _aendere_bewerbung(conn, bewerbung_id, bewerbung, args, heute)


def _aendere_bewerbung(
    conn: sqlite3.Connection,
    bewerbung_id: int | None,
    bewerbung: store.NeueBewerbung,
    args: argparse.Namespace,
    heute: date,
) -> str:
    am = _lies_datum(args.am)
    if am is not None and args.aktion != "beworben":
        raise FeedbackFehler("--am gibt es nur zusammen mit beworben.")

    bezeichnung = f"{bewerbung.titel} ({bewerbung.firma or 'unbekannt'})"

    if bewerbung_id is None:
        if args.aktion != "beworben":
            raise FeedbackFehler(
                f"Zu {bezeichnung} gibt es noch keine Bewerbung. Erfasse sie zuerst mit beworben."
            )
        datum = am or heute
        store.lege_bewerbung_an(conn, bewerbung, args.aktion, datum)
        return f"Bewerbung gespeichert: {bezeichnung}, beworben am {datum.isoformat()}"

    if args.aktion == _ZURUECKNEHMEN:
        store.loesche_bewerbung(conn, bewerbung_id)
        return f"Bewerbung zurückgenommen: {bezeichnung}"

    store.aktualisiere_bewerbung(conn, bewerbung_id, args.aktion, am)
    return f"Status geändert: {bezeichnung} ist jetzt {args.aktion}"


def _speichere_score(
    conn: sqlite3.Connection,
    treffer: store.GespeicherterTreffer,
    werte: list[str],
    heute: date,
) -> str:
    score = _lies_score(werte)
    grund = " ".join(werte[1:]) or None
    store.speichere_feedback(conn, treffer.id, score, grund, heute)
    return f"Feedback gespeichert: {treffer.titel} bekommt von dir Score {score}"


def _lies_score(werte: list[str]) -> int:
    if not werte or not werte[0].isdecimal() or not 1 <= int(werte[0]) <= 5:
        raise FeedbackFehler("Nach score wird eine Zahl von 1 bis 5 erwartet.")
    return int(werte[0])


def _lies_datum(text: str | None) -> date | None:
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise FeedbackFehler(f"Datum im Format JJJJ-MM-TT erwartet, bekam: {text}") from None


if __name__ == "__main__":
    raise SystemExit(main())
