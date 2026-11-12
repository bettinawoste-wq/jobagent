"""Kommando fuer Rueckmeldungen: Bewerbungen, Bewerbungsstatus und eigener Score."""

import argparse
import copy
import re
import sqlite3
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

from jobagent import store
from jobagent.position import position_key

_DB_PATH = Path("jobagent.db")

_STATUSES = [str(status) for status in store.ApplicationStatus]
_WITHDRAW_ENTRY = "zurücknehmen"
_SCORE = "score"

_REPORT_NAME = re.compile(r"\d{4}-\d{2}-\d{2}")

_USAGE = """python -m jobagent.feedback REPORT NUMMER AKTION
       python -m jobagent.feedback REPORT NUMMER score 1-5 [GRUND]
       python -m jobagent.feedback AKTION --firma FIRMA --titel TITEL

AKTION: beworben, gespräch, absage, zusage, zurückgezogen, zurücknehmen
Beispiele:
  python -m jobagent.feedback 2026-11-06 3 beworben --am 2026-11-01
  python -m jobagent.feedback 2026-11-06 2 score 4 "Dienstleister ist okay"
  python -m jobagent.feedback absage --firma "Firma X" --titel "Data Engineer\""""


class FeedbackError(Exception):
    """Ein Aufruf, der sich nicht ausfuehren laesst; die Meldung ist fuer die Nutzerin."""


def main(
    argv: list[str] | None = None,
    *,
    db_path: Path = _DB_PATH,
    today: date | None = None,
) -> int:
    """Fuehrt eine Rueckmeldung aus und gibt den Exit-Code zurueck."""
    arguments = sys.argv[1:] if argv is None else argv
    day = today or date.today()

    if arguments and _REPORT_NAME.match(arguments[0]):
        parsed = _match_parser().parse_args(arguments)
        execute = _match_command
    else:
        parsed = _manual_parser().parse_args(arguments)
        execute = _manual_command

    conn = store.connect(db_path)
    try:
        print(execute(conn, parsed, day))
        return 0
    except FeedbackError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    finally:
        conn.close()


class _HelpFormatter(argparse.HelpFormatter):
    # Die Auswahl-Position traegt metavar "aktion", damit Fehlermeldungen den
    # deutschen Namen nennen; in der Hilfe soll trotzdem die Auswahl stehen.
    def _metavar_formatter(
        self, action: argparse.Action, default_metavar: str
    ) -> Callable[[int], tuple[str, ...]]:
        if action.choices is not None and not action.option_strings:
            action = copy.copy(action)
            action.metavar = None
        return super()._metavar_formatter(action, default_metavar)


# Die Namen in der CLI bleiben deutsch (metavar und Flags), die Attribute
# im Code englisch (dest).
def _match_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(usage=_USAGE, formatter_class=_HelpFormatter)
    parser.add_argument("report")
    parser.add_argument("number", metavar="nummer", type=int)
    parser.add_argument("action", metavar="aktion", choices=[*_STATUSES, _WITHDRAW_ENTRY, _SCORE])
    parser.add_argument("values", metavar="werte", nargs="*")
    parser.add_argument("--am", dest="applied_on", metavar="AM")
    return parser


def _manual_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(usage=_USAGE, formatter_class=_HelpFormatter)
    parser.add_argument("action", metavar="aktion", choices=[*_STATUSES, _WITHDRAW_ENTRY])
    parser.add_argument("--firma", dest="company", metavar="FIRMA", required=True)
    parser.add_argument("--titel", dest="title", metavar="TITEL", required=True)
    parser.add_argument("--am", dest="applied_on", metavar="AM")
    return parser


def _match_command(conn: sqlite3.Connection, args: argparse.Namespace, today: date) -> str:
    report_name = args.report.removesuffix(".md")
    match = store.find_match(conn, report_name, args.number)
    if match is None:
        raise FeedbackError(
            f"Treffer {args.number} in Report {report_name} nicht gefunden. Reports vor "
            "Version 0.3.0 haben keine Nummern; erfasse die Bewerbung dann mit --firma und --titel."
        )

    if args.action == _SCORE:
        return _save_score(conn, match, args.values, today)

    if args.values:
        raise FeedbackError(f"Unerwartete Angaben nach {args.action}: {' '.join(args.values)}")

    application = store.NewApplication(
        position_key=position_key(match.company, match.title),
        company=match.company,
        title=match.title,
        job_ad_id=match.id,
    )
    application_id = store.application_for_job_ad(conn, match.id)
    return _change_application(conn, application_id, application, args, today)


def _manual_command(conn: sqlite3.Connection, args: argparse.Namespace, today: date) -> str:
    application = store.NewApplication(
        position_key=position_key(args.company, args.title),
        company=args.company,
        title=args.title,
        job_ad_id=None,
    )
    application_id = store.application_for_position(conn, application.position_key)
    return _change_application(conn, application_id, application, args, today)


def _change_application(
    conn: sqlite3.Connection,
    application_id: int | None,
    application: store.NewApplication,
    args: argparse.Namespace,
    today: date,
) -> str:
    applied_on = _parse_date(args.applied_on)
    if applied_on is not None and args.action != "beworben":
        raise FeedbackError("--am gibt es nur zusammen mit beworben.")

    label = f"{application.title} ({application.company or 'unbekannt'})"

    if application_id is None:
        if args.action != "beworben":
            raise FeedbackError(
                f"Zu {label} gibt es noch keine Bewerbung. Erfasse sie zuerst mit beworben."
            )
        applied = applied_on or today
        store.create_application(conn, application, args.action, applied)
        return f"Bewerbung gespeichert: {label}, beworben am {applied.isoformat()}"

    if args.action == _WITHDRAW_ENTRY:
        store.delete_application(conn, application_id)
        return f"Bewerbung zurückgenommen: {label}"

    store.update_application(conn, application_id, args.action, applied_on)
    return f"Status geändert: {label} ist jetzt {args.action}"


def _save_score(
    conn: sqlite3.Connection,
    match: store.StoredMatch,
    values: list[str],
    today: date,
) -> str:
    score = _parse_score(values)
    reason = " ".join(values[1:]) or None
    store.save_feedback(conn, match.id, score, reason, today)
    return f"Feedback gespeichert: {match.title} bekommt von dir Score {score}"


def _parse_score(values: list[str]) -> int:
    if not values or not values[0].isdecimal() or not 1 <= int(values[0]) <= 5:
        raise FeedbackError("Nach score wird eine Zahl von 1 bis 5 erwartet.")
    return int(values[0])


def _parse_date(text: str | None) -> date | None:
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise FeedbackError(f"Datum im Format JJJJ-MM-TT erwartet, bekam: {text}") from None


if __name__ == "__main__":
    raise SystemExit(main())
