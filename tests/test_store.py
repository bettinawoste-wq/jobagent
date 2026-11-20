"""Tests fuer store.py mit temporaerer Datenbank.

Was die Datenbank selbst festhaelt (Schema, kein Volltext, Hash), pruefen die Tests
mit einer eigenen Verbindung; alles andere laeuft ueber die Methoden von `Store`.
"""

import ast
import json
import sqlite3
from collections.abc import Callable, Iterator
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
    Store,
    StoredMatch,
    StoreError,
    _Connection,
)

_SRC = Path(__file__).resolve().parent.parent / "src" / "jobagent"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "jobagent.db"


@pytest.fixture
def db(db_path: Path) -> Iterator[Store]:
    with Store(db_path) as opened:
        yield opened


def _query(db_path: Path, sql: str, parameters: tuple = ()) -> list[tuple]:
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(sql, parameters).fetchall()
    finally:
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


def _application(job_ad_id: str | None = "a-1") -> NewApplication:
    return NewApplication("beispiel gmbh|dev", "Beispiel GmbH", "Dev", job_ad_id)


def _hash_of(db_path: Path, job_ad_id: str) -> str | None:
    [(value,)] = _query(
        db_path, "SELECT beschreibung_hash FROM gesehene_anzeigen WHERE id = ?", (job_ad_id,)
    )
    return value


def test_is_new_true_for_unknown_id(db: Store) -> None:
    assert db.is_new("unbekannte-id") is True


def test_remember_job_ad_makes_is_new_false(db: Store) -> None:
    job_ad = _example_job_ad()

    db.remember_job_ad(job_ad, _assessment(4), date(2026, 11, 5))

    assert db.is_new(job_ad.id) is False


def test_remember_job_ad_stores_correct_values(db: Store, db_path: Path) -> None:
    job_ad = _example_job_ad()

    db.remember_job_ad(job_ad, _assessment(4), date(2026, 11, 5))

    assert _query(
        db_path, "SELECT id, titel, firma, link, score, datum FROM gesehene_anzeigen"
    ) == [(job_ad.id, job_ad.title, job_ad.company, job_ad.link, 4, "2026-11-05")]


def test_remember_job_ad_stores_no_full_text(db: Store, db_path: Path) -> None:
    db.remember_job_ad(_example_job_ad(), _assessment(4), date(2026, 11, 5))

    stored = str(_query(db_path, "SELECT * FROM gesehene_anzeigen"))
    assert "Lange Stellenbeschreibung" not in stored


def test_remember_job_ad_stores_assessment_details(db: Store, db_path: Path) -> None:
    db.remember_job_ad(_example_job_ad(), _assessment(), date(2026, 11, 5))

    [(raw,)] = _query(db_path, "SELECT bewertung FROM gesehene_anzeigen")
    assert json.loads(raw) == {
        "passt": ["Python"],
        "passt_nicht": ["Reisen"],
        "luecken": ["Kubernetes"],
        "kurzfazit": "Passt gut für München.",
    }


def test_hash_ignores_whitespace_differences(db: Store, db_path: Path) -> None:
    single_line = replace(_example_job_ad("a-1"), description="Python in München")
    wrapped = replace(_example_job_ad("a-2"), description="  Python\n\nin   München ")

    db.remember_job_ad(single_line, _assessment(), date(2026, 11, 5))
    db.remember_job_ad(wrapped, _assessment(), date(2026, 11, 5))

    assert _hash_of(db_path, "a-1") == _hash_of(db_path, "a-2")


def test_hash_distinguishes_differing_text(db: Store, db_path: Path) -> None:
    old = replace(_example_job_ad("a-1"), description="Python in München")
    new = replace(_example_job_ad("a-2"), description="Python in Berlin")

    db.remember_job_ad(old, _assessment(), date(2026, 11, 5))
    db.remember_job_ad(new, _assessment(), date(2026, 11, 5))

    assert _hash_of(db_path, "a-1") != _hash_of(db_path, "a-2")


@pytest.mark.parametrize("description", [None, "", "  \n "])
def test_no_hash_without_description(db: Store, db_path: Path, description: str | None) -> None:
    job_ad = replace(_example_job_ad(), description=description)

    db.remember_job_ad(job_ad, _assessment(), date(2026, 11, 5))

    assert _hash_of(db_path, job_ad.id) is None


def test_match_numbers_make_job_ads_findable(db: Store) -> None:
    db.remember_job_ad(_example_job_ad("a-1"), _assessment(), date(2026, 11, 5))
    db.remember_job_ad(_example_job_ad("a-2"), _assessment(), date(2026, 11, 5))

    db.save_match_numbers("2026-11-05-2", {"a-1": 2, "a-2": 1})

    title, company = "Softwareentwickler/in (m/w/d)", "Beispiel GmbH"
    assert db.find_match("2026-11-05-2", 2) == StoredMatch("a-1", title, company)
    assert db.find_match("2026-11-05-2", 1) == StoredMatch("a-2", title, company)
    assert db.find_match("2026-11-05-2", 3) is None
    assert db.find_match("2026-11-05", 1) is None


def test_application_for_job_ad_finds_created_application(db: Store) -> None:
    assert db.application_for_job_ad("a-1") is None

    db.create_application(_application("a-1"), ApplicationStatus.APPLIED, date(2026, 11, 1))

    assert db.application_for_job_ad("a-1") == 1
    assert db.application_for_job_ad("a-2") is None


def test_update_application_changes_status_and_keeps_date_without_one(db: Store) -> None:
    db.create_application(_application(), ApplicationStatus.APPLIED, date(2026, 11, 1))

    db.update_application(1, ApplicationStatus.INTERVIEW, None)

    assert db.current_application("beispiel gmbh|dev") == KnownApplication(
        ApplicationStatus.INTERVIEW, date(2026, 11, 1), None
    )


def test_update_application_sets_given_date(db: Store) -> None:
    db.create_application(_application(), ApplicationStatus.INTERVIEW, date(2026, 11, 1))

    db.update_application(1, ApplicationStatus.APPLIED, date(2026, 11, 4))

    assert db.current_application("beispiel gmbh|dev") == KnownApplication(
        ApplicationStatus.APPLIED, date(2026, 11, 4), None
    )


def test_delete_application_removes_it(db: Store) -> None:
    db.create_application(_application(), ApplicationStatus.APPLIED, date(2026, 11, 1))

    db.delete_application(1)

    assert db.application_for_job_ad("a-1") is None
    assert db.latest_application_id("beispiel gmbh|dev") is None


def test_open_feedback_returns_assessment_with_english_fields(db: Store) -> None:
    db.remember_job_ad(_example_job_ad("a-1"), _assessment(2), date(2026, 11, 5))
    db.save_feedback("a-1", 4, "Passt doch", date(2026, 11, 6))

    assert db.open_feedback() == [
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


def test_processed_feedback_is_no_longer_open(db: Store) -> None:
    for job_ad_id in ("a-1", "a-2"):
        db.remember_job_ad(_example_job_ad(job_ad_id), _assessment(), date(2026, 11, 5))
        db.save_feedback(job_ad_id, 3, None, date(2026, 11, 6))

    db.mark_feedback_processed(["a-1"])

    assert [entry.job_ad_id for entry in db.open_feedback()] == ["a-2"]
    assert db.count_open_feedback() == 1


def test_new_feedback_replaces_old_and_is_open_again(db: Store) -> None:
    db.remember_job_ad(_example_job_ad("a-1"), _assessment(), date(2026, 11, 5))
    db.save_feedback("a-1", 1, None, date(2026, 11, 6))
    db.mark_feedback_processed(["a-1"])

    db.save_feedback("a-1", 5, "Doch gut", date(2026, 11, 7))

    [entry] = db.open_feedback()
    assert (entry.own_score, entry.reason) == (5, "Doch gut")


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


def test_store_migrates_old_database_without_data_loss(db_path: Path) -> None:
    _db_before_0_3_0(db_path)

    with Store(db_path) as db:
        assert db.is_new("alt-1") is False

    assert _query(
        db_path,
        "SELECT id, score, datum, report, nummer, beschreibung_hash, bewertung "
        "FROM gesehene_anzeigen",
    ) == [("alt-1", 3, "2026-11-06", None, None, None, None)]


def test_store_is_stable_when_opened_repeatedly(db_path: Path) -> None:
    _db_before_0_3_0(db_path)

    with Store(db_path):
        pass
    with Store(db_path):
        pass


def test_store_creates_database_file(db_path: Path) -> None:
    with Store(db_path) as db:
        assert db.is_new("irgendeine-id") is True

    assert db_path.exists()


def test_store_closes_connection_when_schema_cannot_be_created(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path.write_bytes(b"keine SQLite-Datenbank, nur Text " * 100)
    original_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def recording_connect(*args, **kwargs) -> sqlite3.Connection:
        opened.append(original_connect(*args, **kwargs))
        return opened[-1]

    monkeypatch.setattr(sqlite3, "connect", recording_connect)

    with pytest.raises(StoreError):
        Store(db_path)

    [connection] = opened
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    # Unter Windows sperrt eine offene Verbindung die Datei; sie muss sich loeschen lassen.
    db_path.unlink()


def test_store_names_database_that_is_no_sqlite_file(db_path: Path) -> None:
    db_path.write_bytes(b"keine SQLite-Datenbank, nur Text " * 100)

    with pytest.raises(StoreError, match=r"Datenbank .*jobagent\.db") as error:
        Store(db_path)

    assert "file is not a database" in str(error.value)


def test_store_names_database_that_cannot_be_opened(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="Datenbank") as error:
        Store(tmp_path)  # ein Ordner, keine Datei

    assert str(tmp_path) in str(error.value)


def test_multiple_job_ads_are_tracked_independently(db: Store) -> None:
    db.remember_job_ad(_example_job_ad("a-1"), _assessment(5), date(2026, 11, 5))

    assert db.is_new("a-1") is False
    assert db.is_new("a-2") is True


def _schema(db_path: Path) -> dict[str, list[str]]:
    tables = [
        row[0] for row in _query(db_path, "SELECT name FROM sqlite_master WHERE type='table'")
    ]
    return {
        table: [row[1] for row in _query(db_path, f"PRAGMA table_info({table})")]
        for table in sorted(tables)
    }


def test_db_schema_keeps_german_tables_and_columns(db: Store, db_path: Path) -> None:
    assert _schema(db_path) == {
        "bewerbungen": ["id", "stelle", "firma", "titel", "anzeige_id", "status", "beworben_am"],
        "feedback": ["anzeige_id", "score", "grund", "datum", "verarbeitet"],
        "vollstaendige_laeufe": ["datum", "report"],
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


def test_database_from_old_code_can_be_read_and_written(db_path: Path) -> None:
    _db_from_version_0_4_0(db_path)

    with Store(db_path) as db:
        assert db.is_new("a-1") is False
        assert db.find_match("2026-11-01", 1) == StoredMatch("a-1", "Data Engineer", "Firma X")
        assert db.application_for_job_ad("a-1") == 1
        assert db.latest_application_id("firma x|data engineer") == 1
        assert db.current_application("firma x|data engineer") == KnownApplication(
            ApplicationStatus.APPLIED, date(2026, 11, 1), "hash-1"
        )
        assert db.follow_up_reminders(date(2026, 11, 15), min_days=14, max_days=28) == [
            FollowUpReminder("Firma X", "Data Engineer", date(2026, 11, 1))
        ]
        assert db.count_open_feedback() == 1
        [feedback] = db.open_feedback()
        assert feedback.assessment == Assessment(2, ["Python"], ["Reisen"], [], "Eher nein.")
        assert db.last_complete_run() is None

        db.remember_job_ad(_example_job_ad("a-2"), _assessment(), date(2026, 11, 3))
        db.save_match_numbers("2026-11-03", {"a-2": 1})
        db.create_application(_application("a-2"), ApplicationStatus.APPLIED, date(2026, 11, 3))
        db.mark_feedback_processed(["a-1"])

    with Store(db_path) as db:
        assert db.find_match("2026-11-03", 1) == StoredMatch(
            "a-2", "Softwareentwickler/in (m/w/d)", "Beispiel GmbH"
        )
        assert db.application_for_job_ad("a-2") == 2
        assert db.count_open_feedback() == 0


def test_feedback_without_stored_assessment_has_none(db_path: Path) -> None:
    _db_before_0_3_0(db_path)

    with Store(db_path) as db:
        db.save_feedback("alt-1", 5, None, date(2026, 11, 7))
        [feedback] = db.open_feedback()

    assert feedback.assessment is None
    assert feedback.model_score == 3


def test_application_status_values_stay_german() -> None:
    assert [str(status) for status in ApplicationStatus] == [
        "beworben",
        "gespräch",
        "absage",
        "zusage",
        "zurückgezogen",
    ]


def test_store_remembers_job_ad_across_openings(db_path: Path) -> None:
    with Store(db_path) as first:
        assert first.is_new("a-1") is True
        first.remember_job_ad(_example_job_ad("a-1"), _assessment(), date(2026, 11, 5))

    with Store(db_path) as second:
        assert second.is_new("a-1") is False
        assert second.is_new("a-2") is True


def test_store_closes_its_connection_on_exit(db_path: Path) -> None:
    with Store(db_path) as opened:
        pass

    with pytest.raises(sqlite3.ProgrammingError):
        opened.is_new("a-1")


def _applications_on(db: Store, *applications: tuple[str, ApplicationStatus, date]) -> None:
    """Legt Bewerbungen auf die Stelle "beispiel gmbh|dev" an: (Anzeigen-ID, Status, Datum)."""
    for job_ad_id, status, applied_on in applications:
        db.create_application(_application(job_ad_id), status, applied_on)


def test_current_application_skips_withdrawn_latest_application_does_not(db: Store) -> None:
    _applications_on(
        db,
        ("a-1", ApplicationStatus.INTERVIEW, date(2026, 11, 1)),
        ("a-2", ApplicationStatus.WITHDRAWN, date(2026, 11, 3)),
    )

    assert db.current_application("beispiel gmbh|dev") == KnownApplication(
        ApplicationStatus.INTERVIEW, date(2026, 11, 1), None
    )
    assert db.latest_application_id("beispiel gmbh|dev") == 2


def test_no_current_application_when_only_withdrawn(db: Store) -> None:
    _applications_on(db, ("a-1", ApplicationStatus.WITHDRAWN, date(2026, 11, 1)))

    assert db.current_application("beispiel gmbh|dev") is None
    assert db.latest_application_id("beispiel gmbh|dev") == 1
    assert db.latest_application_id("andere firma|dev") is None


def test_only_the_store_module_knows_sqlite() -> None:
    importers = []
    for path in sorted(_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(name.split(".")[0] == "sqlite3" for name in names):
                importers.append(path.relative_to(_SRC).as_posix())

    assert importers == ["store.py"]


def test_transaction_forgets_everything_when_it_fails(db_path: Path) -> None:
    with Store(db_path) as db:
        with pytest.raises(RuntimeError), db.transaction():
            db.remember_job_ad(_example_job_ad("a-1"), _assessment(), date(2026, 11, 5))
            db.save_match_numbers("2026-11-05", {"a-1": 1})
            raise RuntimeError("Report nicht geschrieben")

        assert db.is_new("a-1") is True

    with Store(db_path) as reopened:
        assert reopened.is_new("a-1") is True
        assert reopened.find_match("2026-11-05", 1) is None


def _locked(self: object) -> None:
    raise StoreError("Datenbank jobagent.db nicht nutzbar: database is locked")


def test_transaction_forgets_everything_when_commit_fails(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Store(db_path) as db:
        with monkeypatch.context() as patch:
            patch.setattr(_Connection, "commit", _locked)
            with pytest.raises(StoreError), db.transaction():
                db.remember_job_ad(_example_job_ad("a-1"), _assessment(), date(2026, 11, 5))

        db.save_feedback("a-2", 3, None, date(2026, 11, 5))  # committet wieder

    with Store(db_path) as reopened:
        assert reopened.is_new("a-1") is True


def _internal(self: object) -> None:
    raise sqlite3.InternalError("interner Fehler")


@pytest.mark.parametrize("failing_rollback", [_locked, _internal])
def test_store_is_closed_when_rollback_fails_too(
    failing_rollback: Callable[[object], None], db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Store(db_path) as db:
        with monkeypatch.context() as patch:
            patch.setattr(_Connection, "commit", _locked)
            patch.setattr(_Connection, "rollback", failing_rollback)
            with pytest.raises(StoreError, match="locked"), db.transaction():
                db.remember_job_ad(_example_job_ad("a-1"), _assessment(), date(2026, 11, 5))

        # Ein spaeterer Commit darf die halbe Transaktion nicht doch noch festschreiben.
        with pytest.raises(sqlite3.ProgrammingError):
            db.save_feedback("a-2", 3, None, date(2026, 11, 5))

    with Store(db_path) as reopened:
        assert reopened.is_new("a-1") is True


def test_transactions_do_not_nest(db: Store) -> None:
    with db.transaction(), pytest.raises(RuntimeError), db.transaction():
        pass


def test_transaction_keeps_everything_when_it_succeeds(db_path: Path) -> None:
    with Store(db_path) as db, db.transaction():
        db.remember_job_ad(_example_job_ad("a-1"), _assessment(), date(2026, 11, 5))
        db.save_match_numbers("2026-11-05", {"a-1": 1})

    with Store(db_path) as reopened:
        match = reopened.find_match("2026-11-05", 1)
        assert match is not None
        assert match.id == "a-1"


# Vollständige Läufe


def test_without_complete_run_there_is_no_last_one(db: Store) -> None:
    assert db.last_complete_run() is None


def test_last_complete_run_is_the_latest_day(db_path: Path) -> None:
    with Store(db_path) as db:
        db.remember_complete_run(date(2026, 11, 16), "2026-11-16")
        db.remember_complete_run(date(2026, 11, 19), "2026-11-19")
        db.remember_complete_run(date(2026, 11, 19), "2026-11-19-2")

    with Store(db_path) as db:
        assert db.last_complete_run() == date(2026, 11, 19)


def test_complete_run_stores_only_day_and_report(db: Store, db_path: Path) -> None:
    db.remember_complete_run(date(2026, 11, 19), "2026-11-19")

    with sqlite3.connect(db_path) as raw:
        rows = raw.execute("SELECT * FROM vollstaendige_laeufe").fetchall()
    assert rows == [("2026-11-19", "2026-11-19")]
