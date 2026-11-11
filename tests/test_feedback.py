"""Tests fuer das Kommando feedback, gegen eine temporaere Datenbank."""

from datetime import date
from pathlib import Path

import pytest

from jobagent import feedback, store
from jobagent.job_ad import JobAd
from jobagent.position import position_key
from jobagent.score import Assessment

_TODAY = date(2026, 11, 8)
_REPORT = "2026-11-06"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "jobagent.db"
    assessment = Assessment(score=3, fits=[], misfits=[], gaps=[], summary="Geht.")
    conn = store.connect(path)
    for job_ad_id, title in [("a-1", "Data Engineer (m/w/d)"), ("a-2", "Consultant")]:
        job_ad = JobAd(id=job_ad_id, title=title, company="Beispiel GmbH", location="M", link="l")
        store.mark_seen(conn, job_ad, assessment, date(2026, 11, 6))
    store.save_match_numbers(conn, _REPORT, {"a-1": 1, "a-2": 2})
    conn.close()
    return path


def _run(db: Path, *arguments: str) -> int:
    return feedback.main(list(arguments), db_path=db, today=_TODAY)


def _query(db: Path, sql: str) -> list[tuple]:
    conn = store.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _applications(db: Path) -> list[tuple]:
    return _query(db, "SELECT anzeige_id, status, beworben_am FROM bewerbungen ORDER BY id")


def _feedback(db: Path) -> list[tuple]:
    return _query(db, "SELECT anzeige_id, score, grund, datum, verarbeitet FROM feedback")


def test_applied_creates_application(db: Path, capsys: pytest.CaptureFixture) -> None:
    assert _run(db, _REPORT, "1", "beworben") == 0

    assert _applications(db) == [("a-1", "beworben", "2026-11-08")]
    assert "Data Engineer" in capsys.readouterr().out


def test_application_stores_position_key_company_and_title(db: Path) -> None:
    _run(db, _REPORT, "1", "beworben")

    assert _query(db, "SELECT stelle, firma, titel FROM bewerbungen") == [
        (
            position_key("Beispiel GmbH", "Data Engineer"),
            "Beispiel GmbH",
            "Data Engineer (m/w/d)",
        )
    ]


def test_applied_with_date(db: Path) -> None:
    _run(db, _REPORT, "1", "beworben", "--am", "2026-11-01")

    assert _applications(db) == [("a-1", "beworben", "2026-11-01")]


def test_applying_again_creates_no_second_application(db: Path) -> None:
    _run(db, _REPORT, "1", "beworben", "--am", "2026-11-01")

    assert _run(db, _REPORT, "1", "beworben") == 0

    assert _applications(db) == [("a-1", "beworben", "2026-11-01")]


def test_applied_with_date_corrects_existing_application(db: Path) -> None:
    _run(db, _REPORT, "1", "beworben")

    _run(db, _REPORT, "1", "beworben", "--am", "2026-11-02")

    assert _applications(db) == [("a-1", "beworben", "2026-11-02")]


@pytest.mark.parametrize("status", ["gespräch", "absage", "zusage", "zurückgezogen"])
def test_status_overwrites_and_keeps_date(db: Path, status: str) -> None:
    _run(db, _REPORT, "1", "beworben", "--am", "2026-11-01")

    assert _run(db, _REPORT, "1", status) == 0

    assert _applications(db) == [("a-1", status, "2026-11-01")]


def test_status_without_application_is_error(db: Path, capsys: pytest.CaptureFixture) -> None:
    assert _run(db, _REPORT, "1", "absage") == 1

    assert _applications(db) == []
    assert "beworben" in capsys.readouterr().err


def test_withdraw_entry_deletes_application(db: Path) -> None:
    _run(db, _REPORT, "1", "beworben")

    assert _run(db, _REPORT, "1", "zurücknehmen") == 0

    assert _applications(db) == []


def test_withdraw_entry_without_application_is_error(db: Path) -> None:
    assert _run(db, _REPORT, "1", "zurücknehmen") == 1


def test_unknown_match_gives_helpful_error(db: Path, capsys: pytest.CaptureFixture) -> None:
    assert _run(db, _REPORT, "99", "beworben") == 1

    error = capsys.readouterr().err
    assert "99" in error
    assert "--firma" in error
    assert _applications(db) == []


def test_report_may_be_given_with_file_extension(db: Path) -> None:
    assert _run(db, f"{_REPORT}.md", "2", "beworben") == 0

    assert _applications(db) == [("a-2", "beworben", "2026-11-08")]


def test_score_with_reason(db: Path) -> None:
    assert _run(db, _REPORT, "2", "score", "4", "Dienstleister ist okay") == 0

    assert _feedback(db) == [("a-2", 4, "Dienstleister ist okay", "2026-11-08", 0)]


def test_score_without_reason(db: Path) -> None:
    assert _run(db, _REPORT, "2", "score", "1") == 0

    assert _feedback(db) == [("a-2", 1, None, "2026-11-08", 0)]


def test_new_score_replaces_old_and_counts_as_unprocessed_again(db: Path) -> None:
    _run(db, _REPORT, "2", "score", "1")
    conn = store.connect(db)
    conn.execute("UPDATE feedback SET verarbeitet = 1")
    conn.commit()
    conn.close()

    _run(db, _REPORT, "2", "score", "5", "Doch gut")

    assert _feedback(db) == [("a-2", 5, "Doch gut", "2026-11-08", 0)]


@pytest.mark.parametrize("arguments", [["0"], ["6"], ["abc"], []])
def test_invalid_score_is_rejected(db: Path, arguments: list[str]) -> None:
    assert _run(db, _REPORT, "2", "score", *arguments) == 1

    assert _feedback(db) == []


def test_manual_application_has_no_job_ad(db: Path) -> None:
    assert _run(db, "beworben", "--firma", "Firma X", "--titel", "Dev (m/w/d)") == 0

    assert _query(db, "SELECT stelle, firma, titel, anzeige_id, status FROM bewerbungen") == [
        (position_key("Firma X", "Dev"), "Firma X", "Dev (m/w/d)", None, "beworben")
    ]


def test_manual_application_with_date(db: Path) -> None:
    _run(db, "beworben", "--firma", "Firma X", "--titel", "Dev", "--am", "2026-10-01")

    assert _applications(db) == [(None, "beworben", "2026-10-01")]


def test_manual_status_finds_application_despite_other_spelling(db: Path) -> None:
    _run(db, "beworben", "--firma", "Firma X GmbH", "--titel", "Dev (m/w/d)")

    assert _run(db, "absage", "--firma", "firma x", "--titel", "DEV (w/m/x)") == 0

    assert _applications(db) == [(None, "absage", "2026-11-08")]


def test_manual_applied_twice_creates_no_second_application(db: Path) -> None:
    _run(db, "beworben", "--firma", "Firma X", "--titel", "Dev")

    assert _run(db, "beworben", "--firma", "Firma X", "--titel", "Dev") == 0

    assert len(_applications(db)) == 1


def test_manual_status_without_application_is_error(db: Path) -> None:
    assert _run(db, "absage", "--firma", "Firma X", "--titel", "Dev") == 1


def test_manual_withdraw_entry(db: Path) -> None:
    _run(db, "beworben", "--firma", "Firma X", "--titel", "Dev")

    assert _run(db, "zurücknehmen", "--firma", "Firma X", "--titel", "Dev") == 0

    assert _applications(db) == []


def test_match_can_be_new_application_for_known_position(db: Path) -> None:
    _run(db, "beworben", "--firma", "Beispiel GmbH", "--titel", "Data Engineer")

    _run(db, _REPORT, "1", "beworben")

    assert len(_applications(db)) == 2


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
def test_invalid_calls_are_rejected(db: Path, arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        feedback.main(arguments, db_path=db, today=_TODAY)

    assert exited.value.code == 2


def test_invalid_date_is_rejected(db: Path) -> None:
    assert _run(db, _REPORT, "1", "beworben", "--am", "1.11.2026") == 1

    assert _applications(db) == []


def test_date_only_allowed_with_applied(db: Path) -> None:
    _run(db, _REPORT, "1", "beworben")

    assert _run(db, _REPORT, "1", "absage", "--am", "2026-11-01") == 1

    assert _applications(db) == [("a-1", "beworben", "2026-11-08")]


def test_status_takes_no_further_arguments(db: Path) -> None:
    assert _run(db, _REPORT, "1", "beworben", "zu", "viel") == 1

    assert _applications(db) == []
