"""Rückmeldung: Bewerbungen, Bewerbungsstatus und eigener Score.

`main` ist Kommandozeile und Zusammenbau: Nur dort werden die Argumente gelesen, der Store
geöffnet und das Datum bestimmt. Die Logik dahinter (`change_application_for_match`,
`change_application_for_position` und `save_feedback_for_match`) bekommt Store und Datum
übergeben.
"""

import argparse
import copy
import logging
import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Final, Literal

from jobagent import store
from jobagent.position import position_key
from jobagent.store import ApplicationStatus, Store, StoreError

logger = logging.getLogger(__name__)

_DB_PATH = Path("jobagent.db")

WITHDRAW_ENTRY: Final = "zurücknehmen"

# Was eine Rückmeldung mit der Bewerbung tut: einen Bewerbungsstatus setzen oder sie
# zurücknehmen, also löschen, als hätte es sie nie gegeben.
type Action = ApplicationStatus | Literal["zurücknehmen"]

_STATUSES = [str(status) for status in ApplicationStatus]
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


# Kommandozeile und Zusammenbau


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

    try:
        with Store(db_path) as db:
            print(execute(db, parsed, day))
            return 0
    except StoreError as error:
        logger.debug("Abgebrochen", exc_info=True)  # Traceback nur im Log, nicht auf der Konsole
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    except FeedbackError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1


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
    parser.add_argument("action", metavar="aktion", choices=[*_STATUSES, WITHDRAW_ENTRY, _SCORE])
    parser.add_argument("values", metavar="werte", nargs="*")
    parser.add_argument("--am", dest="applied_on", metavar="AM")
    return parser


def _manual_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(usage=_USAGE, formatter_class=_HelpFormatter)
    parser.add_argument("action", metavar="aktion", choices=[*_STATUSES, WITHDRAW_ENTRY])
    parser.add_argument("--firma", dest="company", metavar="FIRMA", required=True)
    parser.add_argument("--titel", dest="title", metavar="TITEL", required=True)
    parser.add_argument("--am", dest="applied_on", metavar="AM")
    return parser


def _match_command(db: Store, args: argparse.Namespace, today: date) -> str:
    report_name = args.report.removesuffix(".md")
    if args.action == _SCORE:
        score = _parse_score(args.values)
        reason = " ".join(args.values[1:]) or None
        return save_feedback_for_match(
            db, report_name, args.number, score=score, reason=reason, today=today
        )

    if args.values:
        raise FeedbackError(f"Unerwartete Angaben nach {args.action}: {' '.join(args.values)}")
    return change_application_for_match(
        db,
        report_name,
        args.number,
        _parse_action(args.action),
        applied_on=_parse_date(args.applied_on),
        today=today,
    )


def _manual_command(db: Store, args: argparse.Namespace, today: date) -> str:
    return change_application_for_position(
        db,
        args.company,
        args.title,
        _parse_action(args.action),
        applied_on=_parse_date(args.applied_on),
        today=today,
    )


def _parse_action(text: str) -> Action:
    return WITHDRAW_ENTRY if text == WITHDRAW_ENTRY else ApplicationStatus(text)


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


# Logik: bekommt Store und Datum übergeben


def change_application_for_match(
    db: Store,
    report_name: str,
    match_number: int,
    action: Action,
    *,
    applied_on: date | None,
    today: date,
) -> str:
    """Ändert die Bewerbung auf den Treffer `match_number` im Report `report_name`.

    Gibt die Meldung für die Nutzerin zurück; wirft `FeedbackError`, wenn sich die
    Rückmeldung nicht ausführen lässt.
    """
    match = _find_match(db, report_name, match_number)
    application = store.NewApplication(
        position_key=position_key(match.company, match.title),
        company=match.company,
        title=match.title,
        job_ad_id=match.id,
    )
    application_id = db.application_for_job_ad(match.id)
    return _change_application(db, application_id, application, action, applied_on, today)


def change_application_for_position(
    db: Store,
    company: str,
    title: str,
    action: Action,
    *,
    applied_on: date | None,
    today: date,
) -> str:
    """Ändert die Bewerbung auf die Stelle aus `company` und `title`, ohne Treffer.

    Gemeint ist die letzte Bewerbung auf diese Stelle, auch bei anderer Schreibweise.
    Gibt die Meldung für die Nutzerin zurück; wirft `FeedbackError` wie oben.
    """
    application = store.NewApplication(
        position_key=position_key(company, title),
        company=company,
        title=title,
        job_ad_id=None,
    )
    application_id = db.latest_application_id(application.position_key)
    return _change_application(db, application_id, application, action, applied_on, today)


def save_feedback_for_match(
    db: Store,
    report_name: str,
    match_number: int,
    *,
    score: int,
    reason: str | None,
    today: date,
) -> str:
    """Speichert den eigenen Score zu einem Treffer; das Feedback gilt wieder als offen.

    Gibt die Meldung für die Nutzerin zurück; wirft `FeedbackError`, wenn der Score nicht
    auf der Skala von 1 bis 5 liegt oder der Treffer nicht gefunden wird.
    """
    if score not in range(1, 6):
        raise FeedbackError(f"Der Score liegt zwischen 1 und 5, bekam: {score}")
    match = _find_match(db, report_name, match_number)
    db.save_feedback(match.id, score, reason, today)
    return f"Feedback gespeichert: {match.title} bekommt von dir Score {score}"


def _find_match(db: Store, report_name: str, match_number: int) -> store.StoredMatch:
    match = db.find_match(report_name, match_number)
    if match is None:
        raise FeedbackError(
            f"Treffer {match_number} in Report {report_name} nicht gefunden. Reports vor "
            "Version 0.3.0 haben keine Nummern; erfasse die Bewerbung dann mit --firma und --titel."
        )
    return match


def _change_application(
    db: Store,
    application_id: int | None,
    application: store.NewApplication,
    action: Action,
    applied_on: date | None,
    today: date,
) -> str:
    if applied_on is not None and action != ApplicationStatus.APPLIED:
        raise FeedbackError("--am gibt es nur zusammen mit beworben.")

    label = f"{application.title} ({application.company or 'unbekannt'})"

    if application_id is None:
        if action != ApplicationStatus.APPLIED:
            raise FeedbackError(
                f"Zu {label} gibt es noch keine Bewerbung. Erfasse sie zuerst mit beworben."
            )
        applied = applied_on or today
        db.create_application(application, action, applied)
        return f"Bewerbung gespeichert: {label}, beworben am {applied.isoformat()}"

    if action == WITHDRAW_ENTRY:
        db.delete_application(application_id)
        return f"Bewerbung zurückgenommen: {label}"

    db.update_application(application_id, action, applied_on)
    return f"Status geändert: {label} ist jetzt {action}"


if __name__ == "__main__":
    raise SystemExit(main())
