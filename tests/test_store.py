"""Tests fuer store.py mit temporaerer Datenbank."""

import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from jobagent.job_ad import JobAd
from jobagent.score import Assessment
from jobagent.store import (
    ApplicationStatus,
    Feedback,
    FollowUpReminder,
    KnownApplication,
    NewApplication,
    StoredMatch,
    application_for_job_ad,
    application_for_position,
    connect,
    count_open_feedback,
    create_application,
    find_match,
    follow_up_reminders,
    is_new,
    latest_application,
    mark_feedback_processed,
    mark_seen,
    open_feedback,
    save_feedback,
    save_match_numbers,
)


@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


def _example_job_ad(id_: str = "10001-1003353506-S") -> JobAd:
    return JobAd(
        id=id_,
        title="Softwareentwickler/in (m/w/d)",
        company="Beispiel GmbH",
        location="München",
        link="https://www.arbeitsagentur.de/jobsuche/jobdetail/" + id_,
        description="Lange Stellenbeschreibung, die nicht dauerhaft gespeichert werden darf.",
    )


def _assessment(score: int = 4) -> Assessment:
    return Assessment(
        score=score,
        fits=["Python"],
        misfits=["Reisen"],
        gaps=["Kubernetes"],
        summary="Passt gut für München.",
    )


def _hash_of(conn, job_ad_id: str) -> str | None:
    return conn.execute(
        "SELECT beschreibung_hash FROM gesehene_anzeigen WHERE id = ?", (job_ad_id,)
    ).fetchone()[0]


def test_is_new_true_for_unknown_id(conn) -> None:
    assert is_new(conn, "unbekannte-id") is True


def test_mark_seen_makes_is_new_false(conn) -> None:
    job_ad = _example_job_ad()

    mark_seen(conn, job_ad, assessment=_assessment(4), seen_on=date(2026, 11, 5))

    assert is_new(conn, job_ad.id) is False


def test_mark_seen_stores_correct_values(conn) -> None:
    job_ad = _example_job_ad()

    mark_seen(conn, job_ad, assessment=_assessment(4), seen_on=date(2026, 11, 5))

    row = conn.execute(
        "SELECT id, titel, firma, link, score, datum FROM gesehene_anzeigen WHERE id = ?",
        (job_ad.id,),
    ).fetchone()
    assert row == (
        job_ad.id,
        job_ad.title,
        job_ad.company,
        job_ad.link,
        4,
        "2026-11-05",
    )


def test_mark_seen_stores_no_full_text(conn) -> None:
    mark_seen(conn, _example_job_ad(), assessment=_assessment(4), seen_on=date(2026, 11, 5))

    columns = {row[1] for row in conn.execute("PRAGMA table_info(gesehene_anzeigen)")}
    assert columns == {
        "id",
        "titel",
        "firma",
        "link",
        "score",
        "datum",
        "report",
        "nummer",
        "beschreibung_hash",
        "bewertung",
    }
    stored = str(conn.execute("SELECT * FROM gesehene_anzeigen").fetchone())
    assert "Lange Stellenbeschreibung" not in stored


def test_mark_seen_stores_assessment_details(conn) -> None:
    job_ad = _example_job_ad()

    mark_seen(conn, job_ad, assessment=_assessment(), seen_on=date(2026, 11, 5))

    raw = conn.execute(
        "SELECT bewertung FROM gesehene_anzeigen WHERE id = ?", (job_ad.id,)
    ).fetchone()[0]
    assert json.loads(raw) == {
        "passt": ["Python"],
        "passt_nicht": ["Reisen"],
        "luecken": ["Kubernetes"],
        "kurzfazit": "Passt gut für München.",
    }


def test_hash_ignores_whitespace_differences(conn) -> None:
    single_line = replace(_example_job_ad("a-1"), description="Python in München")
    wrapped = replace(_example_job_ad("a-2"), description="  Python\n\nin   München ")

    mark_seen(conn, single_line, assessment=_assessment(), seen_on=date(2026, 11, 5))
    mark_seen(conn, wrapped, assessment=_assessment(), seen_on=date(2026, 11, 5))

    assert _hash_of(conn, "a-1") == _hash_of(conn, "a-2")


def test_hash_distinguishes_differing_text(conn) -> None:
    old = replace(_example_job_ad("a-1"), description="Python in München")
    new = replace(_example_job_ad("a-2"), description="Python in Berlin")

    mark_seen(conn, old, assessment=_assessment(), seen_on=date(2026, 11, 5))
    mark_seen(conn, new, assessment=_assessment(), seen_on=date(2026, 11, 5))

    assert _hash_of(conn, "a-1") != _hash_of(conn, "a-2")


@pytest.mark.parametrize("description", [None, "", "  \n "])
def test_no_hash_without_description(conn, description: str | None) -> None:
    job_ad = replace(_example_job_ad(), description=description)

    mark_seen(conn, job_ad, assessment=_assessment(), seen_on=date(2026, 11, 5))

    assert _hash_of(conn, job_ad.id) is None


def test_save_match_numbers_assigns_report_and_number(conn) -> None:
    mark_seen(conn, _example_job_ad("a-1"), assessment=_assessment(), seen_on=date(2026, 11, 5))
    mark_seen(conn, _example_job_ad("a-2"), assessment=_assessment(), seen_on=date(2026, 11, 5))

    save_match_numbers(conn, "2026-11-05-2", {"a-1": 2, "a-2": 1})

    rows = conn.execute("SELECT id, report, nummer FROM gesehene_anzeigen ORDER BY id").fetchall()
    assert rows == [("a-1", "2026-11-05-2", 2), ("a-2", "2026-11-05-2", 1)]


def test_open_feedback_returns_assessment_with_english_fields(conn) -> None:
    mark_seen(conn, _example_job_ad("a-1"), assessment=_assessment(2), seen_on=date(2026, 11, 5))
    save_feedback(conn, "a-1", 4, "Passt doch", date(2026, 11, 6))

    assert open_feedback(conn) == [
        Feedback(
            job_ad_id="a-1",
            title="Softwareentwickler/in (m/w/d)",
            company="Beispiel GmbH",
            model_score=2,
            assessment=_assessment(2),
            own_score=4,
            reason="Passt doch",
        )
    ]


def _db_before_0_3_0(path: Path) -> None:
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE gesehene_anzeigen (id TEXT PRIMARY KEY, titel TEXT NOT NULL, firma TEXT, "
        "link TEXT NOT NULL, score INTEGER NOT NULL, datum TEXT NOT NULL)"
    )
    old.execute(
        "INSERT INTO gesehene_anzeigen VALUES ('alt-1', 'Titel', 'Firma', 'link', 3, '2026-11-06')"
    )
    old.commit()
    old.close()


def test_connect_migrates_old_database_without_data_loss(tmp_path: Path) -> None:
    db_path = tmp_path / "alt.db"
    _db_before_0_3_0(db_path)

    connection = connect(db_path)
    try:
        row = connection.execute(
            "SELECT id, score, datum, report, nummer, beschreibung_hash, bewertung "
            "FROM gesehene_anzeigen"
        ).fetchone()
        assert row == ("alt-1", 3, "2026-11-06", None, None, None, None)
        assert is_new(connection, "alt-1") is False
    finally:
        connection.close()


def test_connect_is_stable_when_opened_repeatedly(tmp_path: Path) -> None:
    db_path = tmp_path / "alt.db"
    _db_before_0_3_0(db_path)

    connect(db_path).close()
    connect(db_path).close()


def test_connect_creates_table_in_file(tmp_path: Path) -> None:
    db_path = tmp_path / "jobagent.db"

    connection = connect(db_path)
    try:
        assert is_new(connection, "irgendeine-id") is True
    finally:
        connection.close()

    assert db_path.exists()


def test_multiple_job_ads_are_tracked_independently(conn) -> None:
    mark_seen(conn, _example_job_ad("a-1"), assessment=_assessment(5), seen_on=date(2026, 11, 5))

    assert is_new(conn, "a-1") is False
    assert is_new(conn, "a-2") is True


def _schema(conn: sqlite3.Connection) -> dict[str, list[str]]:
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return {
        table: [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        for table in sorted(tables)
    }


def test_db_schema_keeps_german_tables_and_columns(conn) -> None:
    assert _schema(conn) == {
        "bewerbungen": ["id", "stelle", "firma", "titel", "anzeige_id", "status", "beworben_am"],
        "feedback": ["anzeige_id", "score", "grund", "datum", "verarbeitet"],
        "gesehene_anzeigen": [
            "id",
            "titel",
            "firma",
            "link",
            "score",
            "datum",
            "report",
            "nummer",
            "beschreibung_hash",
            "bewertung",
        ],
    }


def _db_from_version_0_4_0(path: Path) -> None:
    """Datenbank, wie sie der Code vor der englischen Benennung angelegt und befuellt hat."""
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE gesehene_anzeigen (
            id TEXT PRIMARY KEY, titel TEXT NOT NULL, firma TEXT, link TEXT NOT NULL,
            score INTEGER NOT NULL, datum TEXT NOT NULL,
            report TEXT, nummer INTEGER, beschreibung_hash TEXT, bewertung TEXT
        );
        CREATE TABLE bewerbungen (
            id INTEGER PRIMARY KEY, stelle TEXT NOT NULL, firma TEXT, titel TEXT NOT NULL,
            anzeige_id TEXT UNIQUE, status TEXT NOT NULL, beworben_am TEXT NOT NULL
        );
        CREATE TABLE feedback (
            anzeige_id TEXT PRIMARY KEY, score INTEGER NOT NULL, grund TEXT,
            datum TEXT NOT NULL, verarbeitet INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO gesehene_anzeigen VALUES (
            'a-1', 'Data Engineer', 'Firma X', 'link', 2, '2026-11-01',
            '2026-11-01', 1, 'hash-1',
            '{"passt": ["Python"], "passt_nicht": ["Reisen"], "luecken": [],'
            || ' "kurzfazit": "Eher nein."}'
        );
        INSERT INTO bewerbungen (stelle, firma, titel, anzeige_id, status, beworben_am)
            VALUES ('firma x|data engineer', 'Firma X', 'Data Engineer', 'a-1', 'beworben',
                    '2026-11-01');
        INSERT INTO feedback (anzeige_id, score, grund, datum)
            VALUES ('a-1', 4, 'Doch gut', '2026-11-02');
        """
    )
    old.commit()
    old.close()


def test_database_from_old_code_can_be_read_and_written(tmp_path: Path) -> None:
    db_path = tmp_path / "jobagent.db"
    _db_from_version_0_4_0(db_path)
    connection = connect(db_path)
    try:
        assert find_match(connection, "2026-11-01", 1) == StoredMatch(
            "a-1", "Data Engineer", "Firma X"
        )
        assert application_for_job_ad(connection, "a-1") == 1
        assert application_for_position(connection, "firma x|data engineer") == 1
        assert latest_application(connection, "firma x|data engineer") == KnownApplication(
            ApplicationStatus.APPLIED, date(2026, 11, 1), "hash-1"
        )
        assert follow_up_reminders(connection, date(2026, 11, 15), min_days=14, max_days=28) == [
            FollowUpReminder("Firma X", "Data Engineer", date(2026, 11, 1))
        ]
        assert count_open_feedback(connection) == 1
        [feedback] = open_feedback(connection)
        assert feedback.assessment == Assessment(2, ["Python"], ["Reisen"], [], "Eher nein.")

        mark_seen(connection, _example_job_ad("a-2"), _assessment(), date(2026, 11, 3))
        save_match_numbers(connection, "2026-11-03", {"a-2": 1})
        create_application(
            connection,
            NewApplication("beispiel gmbh|dev", "Beispiel GmbH", "Dev", "a-2"),
            ApplicationStatus.APPLIED,
            date(2026, 11, 3),
        )
        mark_feedback_processed(connection, ["a-1"])

        assert find_match(connection, "2026-11-03", 1) == StoredMatch(
            "a-2", "Softwareentwickler/in (m/w/d)", "Beispiel GmbH"
        )
        assert application_for_job_ad(connection, "a-2") == 2
        assert count_open_feedback(connection) == 0
    finally:
        connection.close()


def test_feedback_without_stored_assessment_has_none(tmp_path: Path) -> None:
    db_path = tmp_path / "alt.db"
    _db_before_0_3_0(db_path)
    connection = connect(db_path)
    try:
        save_feedback(connection, "alt-1", 5, None, date(2026, 11, 7))

        [feedback] = open_feedback(connection)

        assert feedback.assessment is None
        assert feedback.model_score == 3
    finally:
        connection.close()


def test_application_status_values_stay_german() -> None:
    assert [str(status) for status in ApplicationStatus] == [
        "beworben",
        "gespräch",
        "absage",
        "zusage",
        "zurückgezogen",
    ]
