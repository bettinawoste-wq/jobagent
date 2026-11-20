"""Tests für die Sperre `RunLock` direkt am `with`-Block."""

from pathlib import Path

import pytest

from jobagent.run_lock import RunLock, RunLockedError, RunLockFileError


def test_second_lock_on_the_same_database_fails_and_names_the_lock_file(tmp_path: Path) -> None:
    db_path = tmp_path / "jobagent.db"

    with RunLock(db_path):
        with pytest.raises(RunLockedError) as caught:
            with RunLock(db_path):
                pass

    assert "Es läuft schon ein anderer Lauf" in str(caught.value)
    assert str(tmp_path / "jobagent.db.runlock") in str(caught.value)


def test_lock_is_free_again_after_leaving_the_block(tmp_path: Path) -> None:
    db_path = tmp_path / "jobagent.db"

    with RunLock(db_path):
        pass

    with RunLock(db_path):
        pass


def test_lock_is_free_again_after_an_error_in_the_block(tmp_path: Path) -> None:
    db_path = tmp_path / "jobagent.db"

    with pytest.raises(ValueError), RunLock(db_path):
        raise ValueError("Lauf gescheitert")

    with RunLock(db_path):
        pass


def test_locks_of_different_databases_do_not_block_each_other(tmp_path: Path) -> None:
    with RunLock(tmp_path / "a.db"), RunLock(tmp_path / "b.db"):
        pass


def test_missing_folder_of_the_database_names_the_database(tmp_path: Path) -> None:
    db_path = tmp_path / "fehlt" / "jobagent.db"

    with pytest.raises(RunLockFileError) as caught:
        with RunLock(db_path):
            pass

    assert str(caught.value).startswith(f"Datenbank {db_path} nicht nutzbar")
    assert "Ordner" in str(caught.value)
