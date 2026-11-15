"""Tests für die Rückmeldung.

Die Logik bekommt einen `Store` auf echtem SQLite und ein festes Datum übergeben. Über die
Kommandozeile `main` gehen nur die Tests, die das Lesen der Argumente und die Exit-Codes
prüfen.
"""

import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from jobagent import feedback
from jobagent.feedback import (
    WITHDRAW_ENTRY,
    FeedbackError,
    change_application_for_match,
    change_application_for_position,
    save_feedback_for_match,
)
from jobagent.job_ad import JobAd
from jobagent.position import position_key
from jobagent.score import Assessment
from jobagent.store import ApplicationStatus, Store

_TODAY = date(2026, 11, 8)
_REPORT = "2026-11-06"

APPLIED = ApplicationStatus.APPLIED


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "jobagent.db"
    assessment = Assessment(score=3, fits=[], misfits=[], gaps=[], summary="Geht.")
    with Store(path) as opened:
        for job_ad_id, title in [("a-1", "Data Engineer (m/w/d)"), ("a-2", "Consultant")]:
            job_ad = JobAd(
                id=job_ad_id, title=title, company="Beispiel GmbH", location="M", link="l"
            )
            opened.remember_job_ad(job_ad, assessment, date(2026, 11, 6))
        opened.save_match_numbers(_REPORT, {"a-1": 1, "a-2": 2})
    return path


@pytest.fixture
def db(db_path: Path) -> Iterator[Store]:
    with Store(db_path) as opened:
        yield opened


def _for_match(
    db: Store,
    number: int,
    action: feedback.Action,
    applied_on: date | None = None,
) -> str:
    return change_application_for_match(
        db, _REPORT, number, action, applied_on=applied_on, today=_TODAY
    )


def _for_position(
    db: Store,
    company: str,
    title: str,
    action: feedback.Action,
    applied_on: date | None = None,
) -> str:
    return change_application_for_position(
        db, company, title, action, applied_on=applied_on, today=_TODAY
    )


def _query(db_path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _applications(db_path: Path) -> list[tuple]:
    return _query(db_path, "SELECT anzeige_id, status, beworben_am FROM bewerbungen ORDER BY id")


def _feedback(db_path: Path) -> list[tuple]:
    return _query(db_path, "SELECT anzeige_id, score, grund, datum, verarbeitet FROM feedback")


# Bewerbungen zu einem Treffer


def test_applied_creates_application(db: Store, db_path: Path) -> None:
    message = _for_match(db, 1, APPLIED)

    assert _applications(db_path) == [("a-1", "beworben", "2026-11-08")]
    assert message == "Bewerbung gespeichert: Data Engineer (m/w/d) (Beispiel GmbH), " + (
        "beworben am 2026-11-08"
    )


def test_application_stores_position_key_company_and_title(db: Store, db_path: Path) -> None:
    _for_match(db, 1, APPLIED)

    assert _query(db_path, "SELECT stelle, firma, titel FROM bewerbungen") == [
        (
            position_key("Beispiel GmbH", "Data Engineer"),
            "Beispiel GmbH",
            "Data Engineer (m/w/d)",
        )
    ]


def test_applied_with_date(db: Store, db_path: Path) -> None:
    _for_match(db, 1, APPLIED, date(2026, 11, 1))

    assert _applications(db_path) == [("a-1", "beworben", "2026-11-01")]


def test_applying_again_creates_no_second_application(db: Store, db_path: Path) -> None:
    _for_match(db, 1, APPLIED, date(2026, 11, 1))

    _for_match(db, 1, APPLIED)

    assert _applications(db_path) == [("a-1", "beworben", "2026-11-01")]


def test_applied_with_date_corrects_existing_application(db: Store, db_path: Path) -> None:
    _for_match(db, 1, APPLIED)

    _for_match(db, 1, APPLIED, date(2026, 11, 2))

    assert _applications(db_path) == [("a-1", "beworben", "2026-11-02")]


@pytest.mark.parametrize(
    "status",
    [
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
        ApplicationStatus.OFFER,
        ApplicationStatus.WITHDRAWN,
    ],
)
def test_status_overwrites_and_keeps_date(
    db: Store, db_path: Path, status: ApplicationStatus
) -> None:
    _for_match(db, 1, APPLIED, date(2026, 11, 1))

    message = _for_match(db, 1, status)

    assert _applications(db_path) == [("a-1", str(status), "2026-11-01")]
    assert message == f"Status geändert: Data Engineer (m/w/d) (Beispiel GmbH) ist jetzt {status}"


def test_status_without_application_is_error(db: Store, db_path: Path) -> None:
    with pytest.raises(FeedbackError, match="zuerst mit beworben"):
        _for_match(db, 1, ApplicationStatus.REJECTED)

    assert _applications(db_path) == []


def test_withdraw_entry_deletes_application(db: Store, db_path: Path) -> None:
    _for_match(db, 1, APPLIED)

    message = _for_match(db, 1, WITHDRAW_ENTRY)

    assert _applications(db_path) == []
    assert message == "Bewerbung zurückgenommen: Data Engineer (m/w/d) (Beispiel GmbH)"


def test_withdraw_entry_without_application_is_error(db: Store) -> None:
    with pytest.raises(FeedbackError):
        _for_match(db, 1, WITHDRAW_ENTRY)


def test_unknown_match_gives_helpful_error(db: Store, db_path: Path) -> None:
    with pytest.raises(FeedbackError, match="Treffer 99 .*--firma"):
        _for_match(db, 99, APPLIED)

    assert _applications(db_path) == []


def test_date_only_allowed_with_applied(db: Store, db_path: Path) -> None:
    _for_match(db, 1, APPLIED)

    with pytest.raises(FeedbackError, match="--am"):
        _for_match(db, 1, ApplicationStatus.REJECTED, date(2026, 11, 1))

    assert _applications(db_path) == [("a-1", "beworben", "2026-11-08")]


def test_match_can_be_new_application_for_known_position(db: Store, db_path: Path) -> None:
    _for_position(db, "Beispiel GmbH", "Data Engineer", APPLIED)

    _for_match(db, 1, APPLIED)

    assert len(_applications(db_path)) == 2


# Feedback zu einem Treffer


def test_feedback_with_reason(db: Store, db_path: Path) -> None:
    message = save_feedback_for_match(
        db, _REPORT, 2, score=4, reason="Dienstleister ist okay", today=_TODAY
    )

    assert _feedback(db_path) == [("a-2", 4, "Dienstleister ist okay", "2026-11-08", 0)]
    assert message == "Feedback gespeichert: Consultant bekommt von dir Score 4"


def test_feedback_without_reason(db: Store, db_path: Path) -> None:
    save_feedback_for_match(db, _REPORT, 2, score=1, reason=None, today=_TODAY)

    assert _feedback(db_path) == [("a-2", 1, None, "2026-11-08", 0)]


def test_new_feedback_replaces_old_and_counts_as_unprocessed_again(
    db: Store, db_path: Path
) -> None:
    save_feedback_for_match(db, _REPORT, 2, score=1, reason=None, today=_TODAY)
    db.mark_feedback_processed(["a-2"])

    save_feedback_for_match(db, _REPORT, 2, score=5, reason="Doch gut", today=_TODAY)

    assert _feedback(db_path) == [("a-2", 5, "Doch gut", "2026-11-08", 0)]


def test_feedback_for_unknown_match_is_error(db: Store, db_path: Path) -> None:
    with pytest.raises(FeedbackError, match="Treffer 99"):
        save_feedback_for_match(db, _REPORT, 99, score=4, reason=None, today=_TODAY)

    assert _feedback(db_path) == []


@pytest.mark.parametrize("score", [0, 6])
def test_feedback_outside_score_scale_is_error(db: Store, db_path: Path, score: int) -> None:
    with pytest.raises(FeedbackError, match="zwischen 1 und 5"):
        save_feedback_for_match(db, _REPORT, 2, score=score, reason=None, today=_TODAY)

    assert _feedback(db_path) == []


# Bewerbungen ohne Treffer, nur über Firma und Titel


def test_manual_application_has_no_job_ad(db: Store, db_path: Path) -> None:
    _for_position(db, "Firma X", "Dev (m/w/d)", APPLIED)

    assert _query(db_path, "SELECT stelle, firma, titel, anzeige_id, status FROM bewerbungen") == [
        (position_key("Firma X", "Dev"), "Firma X", "Dev (m/w/d)", None, "beworben")
    ]


def test_manual_application_with_date(db: Store, db_path: Path) -> None:
    _for_position(db, "Firma X", "Dev", APPLIED, date(2026, 10, 1))

    assert _applications(db_path) == [(None, "beworben", "2026-10-01")]


def test_manual_status_finds_application_despite_other_spelling(db: Store, db_path: Path) -> None:
    _for_position(db, "Firma X GmbH", "Dev (m/w/d)", APPLIED)

    _for_position(db, "firma x", "DEV (w/m/x)", ApplicationStatus.REJECTED)

    assert _applications(db_path) == [(None, "absage", "2026-11-08")]


def test_manual_applied_twice_creates_no_second_application(db: Store, db_path: Path) -> None:
    _for_position(db, "Firma X", "Dev", APPLIED)

    _for_position(db, "Firma X", "Dev", APPLIED)

    assert len(_applications(db_path)) == 1


def test_manual_status_without_application_is_error(db: Store) -> None:
    with pytest.raises(FeedbackError):
        _for_position(db, "Firma X", "Dev", ApplicationStatus.REJECTED)


def test_manual_withdraw_entry(db: Store, db_path: Path) -> None:
    _for_position(db, "Firma X", "Dev", APPLIED)

    _for_position(db, "Firma X", "Dev", WITHDRAW_ENTRY)

    assert _applications(db_path) == []


# Kommandozeile


def _main(db_path: Path, *arguments: str) -> int:
    return feedback.main(list(arguments), db_path=db_path, today=_TODAY)


def test_main_records_application_and_prints_message(
    db_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert _main(db_path, _REPORT, "1", "beworben", "--am", "2026-11-01") == 0

    assert _applications(db_path) == [("a-1", "beworben", "2026-11-01")]
    assert "Data Engineer" in capsys.readouterr().out


def test_main_records_manual_application(db_path: Path) -> None:
    assert _main(db_path, "beworben", "--firma", "Firma X", "--titel", "Dev") == 0
    assert _main(db_path, "zurückgezogen", "--firma", "Firma X", "--titel", "Dev") == 0

    assert _applications(db_path) == [(None, "zurückgezogen", "2026-11-08")]


def test_main_withdraws_entry(db_path: Path) -> None:
    _main(db_path, _REPORT, "1", "beworben")

    assert _main(db_path, _REPORT, "1", "zurücknehmen") == 0

    assert _applications(db_path) == []


def test_main_reports_error_with_exit_code_1(db_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert _main(db_path, _REPORT, "99", "beworben") == 1

    error = capsys.readouterr().err
    assert error.startswith("Fehler: Treffer 99")
    assert "--firma" in error


def test_main_aborts_with_message_when_database_is_unusable(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    folder = tmp_path / "jobagent.db"
    folder.mkdir()

    assert _main(folder, _REPORT, "1", "beworben") == 1

    error = capsys.readouterr().err
    assert error.startswith(f"Fehler: Datenbank {folder} nicht nutzbar")
    assert "Traceback" not in error


def test_report_may_be_given_with_file_extension(db_path: Path) -> None:
    assert _main(db_path, f"{_REPORT}.md", "2", "beworben") == 0

    assert _applications(db_path) == [("a-2", "beworben", "2026-11-08")]


def test_main_saves_feedback_with_reason_from_several_words(db_path: Path) -> None:
    assert _main(db_path, _REPORT, "2", "score", "4", "Dienstleister", "ist", "okay") == 0

    assert _feedback(db_path) == [("a-2", 4, "Dienstleister ist okay", "2026-11-08", 0)]


def test_main_saves_feedback_without_reason(db_path: Path) -> None:
    assert _main(db_path, _REPORT, "2", "score", "1") == 0

    assert _feedback(db_path) == [("a-2", 1, None, "2026-11-08", 0)]


@pytest.mark.parametrize("arguments", [["0"], ["6"], ["abc"], []])
def test_invalid_score_is_rejected(db_path: Path, arguments: list[str]) -> None:
    assert _main(db_path, _REPORT, "2", "score", *arguments) == 1

    assert _feedback(db_path) == []


@pytest.mark.parametrize(
    "arguments",
    [
        ["beworben", "--firma", "Firma X"],
        ["beworben", "--titel", "Dev"],
        ["score", "--firma", "Firma X", "--titel", "Dev"],
        ["quatsch", "--firma", "Firma X", "--titel", "Dev"],
        [_REPORT, "1", "quatsch"],
        [_REPORT, "eins", "beworben"],
        [_REPORT, "1"],
        [],
    ],
)
def test_invalid_calls_are_rejected(db_path: Path, arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        feedback.main(arguments, db_path=db_path, today=_TODAY)

    assert exited.value.code == 2


def test_invalid_date_is_rejected(db_path: Path) -> None:
    assert _main(db_path, _REPORT, "1", "beworben", "--am", "1.11.2026") == 1

    assert _applications(db_path) == []


def test_status_takes_no_further_arguments(db_path: Path) -> None:
    assert _main(db_path, _REPORT, "1", "beworben", "zu", "viel") == 1

    assert _applications(db_path) == []
