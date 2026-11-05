"""Tests fuer store.py mit temporaerer Datenbank."""

from datetime import date
from pathlib import Path

import pytest

from jobagent.fetch import Anzeige
from jobagent.store import connect, is_new, mark_seen


@pytest.fixture
def conn():
    verbindung = connect(":memory:")
    yield verbindung
    verbindung.close()


def _beispiel_anzeige(id_: str = "10001-1003353506-S") -> Anzeige:
    return Anzeige(
        id=id_,
        titel="Softwareentwickler/in (m/w/d)",
        firma="Beispiel GmbH",
        ort="München",
        link="https://www.arbeitsagentur.de/jobsuche/jobdetail/" + id_,
        beschreibung="Lange Stellenbeschreibung, die nicht dauerhaft gespeichert werden darf.",
    )


def test_is_new_true_fuer_unbekannte_id(conn) -> None:
    assert is_new(conn, "unbekannte-id") is True


def test_mark_seen_macht_is_new_false(conn) -> None:
    anzeige = _beispiel_anzeige()

    mark_seen(conn, anzeige, score=4, datum=date(2026, 11, 5))

    assert is_new(conn, anzeige.id) is False


def test_mark_seen_speichert_korrekte_werte(conn) -> None:
    anzeige = _beispiel_anzeige()

    mark_seen(conn, anzeige, score=4, datum=date(2026, 11, 5))

    zeile = conn.execute(
        "SELECT id, titel, firma, link, score, datum FROM gesehene_anzeigen WHERE id = ?",
        (anzeige.id,),
    ).fetchone()
    assert zeile == (
        anzeige.id,
        anzeige.titel,
        anzeige.firma,
        anzeige.link,
        4,
        "2026-11-05",
    )


def test_mark_seen_speichert_keinen_volltext(conn) -> None:
    mark_seen(conn, _beispiel_anzeige(), score=4, datum=date(2026, 11, 5))

    spalten = {zeile[1] for zeile in conn.execute("PRAGMA table_info(gesehene_anzeigen)")}
    assert spalten == {"id", "titel", "firma", "link", "score", "datum"}


def test_connect_erstellt_tabelle_in_datei(tmp_path: Path) -> None:
    db_pfad = tmp_path / "jobagent.db"

    verbindung = connect(db_pfad)
    try:
        assert is_new(verbindung, "irgendeine-id") is True
    finally:
        verbindung.close()

    assert db_pfad.exists()


def test_mehrere_anzeigen_werden_unabhaengig_verfolgt(conn) -> None:
    mark_seen(conn, _beispiel_anzeige("a-1"), score=5, datum=date(2026, 11, 5))

    assert is_new(conn, "a-1") is False
    assert is_new(conn, "a-2") is True
