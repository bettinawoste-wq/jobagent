"""Tests fuer store.py mit temporaerer Datenbank."""

import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from jobagent.job_ad import JobAd
from jobagent.score import Assessment
from jobagent.store import connect, is_new, mark_seen, merke_treffernummern


@pytest.fixture
def conn():
    verbindung = connect(":memory:")
    yield verbindung
    verbindung.close()


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


def _hash_von(conn, anzeige_id: str) -> str | None:
    return conn.execute(
        "SELECT beschreibung_hash FROM gesehene_anzeigen WHERE id = ?", (anzeige_id,)
    ).fetchone()[0]


def test_is_new_true_fuer_unbekannte_id(conn) -> None:
    assert is_new(conn, "unbekannte-id") is True


def test_mark_seen_macht_is_new_false(conn) -> None:
    job_ad = _example_job_ad()

    mark_seen(conn, job_ad, assessment=_assessment(4), datum=date(2026, 11, 5))

    assert is_new(conn, job_ad.id) is False


def test_mark_seen_speichert_korrekte_werte(conn) -> None:
    job_ad = _example_job_ad()

    mark_seen(conn, job_ad, assessment=_assessment(4), datum=date(2026, 11, 5))

    zeile = conn.execute(
        "SELECT id, titel, firma, link, score, datum FROM gesehene_anzeigen WHERE id = ?",
        (job_ad.id,),
    ).fetchone()
    assert zeile == (
        job_ad.id,
        job_ad.title,
        job_ad.company,
        job_ad.link,
        4,
        "2026-11-05",
    )


def test_mark_seen_speichert_keinen_volltext(conn) -> None:
    mark_seen(conn, _example_job_ad(), assessment=_assessment(4), datum=date(2026, 11, 5))

    spalten = {zeile[1] for zeile in conn.execute("PRAGMA table_info(gesehene_anzeigen)")}
    assert spalten == {
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
    gespeichert = str(conn.execute("SELECT * FROM gesehene_anzeigen").fetchone())
    assert "Lange Stellenbeschreibung" not in gespeichert


def test_mark_seen_stores_assessment_details(conn) -> None:
    job_ad = _example_job_ad()

    mark_seen(conn, job_ad, assessment=_assessment(), datum=date(2026, 11, 5))

    roh = conn.execute(
        "SELECT bewertung FROM gesehene_anzeigen WHERE id = ?", (job_ad.id,)
    ).fetchone()[0]
    assert json.loads(roh) == {
        "passt": ["Python"],
        "passt_nicht": ["Reisen"],
        "luecken": ["Kubernetes"],
        "kurzfazit": "Passt gut für München.",
    }


def test_hash_ignoriert_unterschiede_im_leerraum(conn) -> None:
    einzeilig = replace(_example_job_ad("a-1"), description="Python in München")
    umbrochen = replace(_example_job_ad("a-2"), description="  Python\n\nin   München ")

    mark_seen(conn, einzeilig, assessment=_assessment(), datum=date(2026, 11, 5))
    mark_seen(conn, umbrochen, assessment=_assessment(), datum=date(2026, 11, 5))

    assert _hash_von(conn, "a-1") == _hash_von(conn, "a-2")


def test_hash_distinguishes_differing_text(conn) -> None:
    alt = replace(_example_job_ad("a-1"), description="Python in München")
    neu = replace(_example_job_ad("a-2"), description="Python in Berlin")

    mark_seen(conn, alt, assessment=_assessment(), datum=date(2026, 11, 5))
    mark_seen(conn, neu, assessment=_assessment(), datum=date(2026, 11, 5))

    assert _hash_von(conn, "a-1") != _hash_von(conn, "a-2")


@pytest.mark.parametrize("beschreibung", [None, "", "  \n "])
def test_kein_hash_ohne_beschreibung(conn, beschreibung: str | None) -> None:
    job_ad = replace(_example_job_ad(), description=beschreibung)

    mark_seen(conn, job_ad, assessment=_assessment(), datum=date(2026, 11, 5))

    assert _hash_von(conn, job_ad.id) is None


def test_merke_treffernummern_ordnet_report_und_nummer_zu(conn) -> None:
    mark_seen(conn, _example_job_ad("a-1"), assessment=_assessment(), datum=date(2026, 11, 5))
    mark_seen(conn, _example_job_ad("a-2"), assessment=_assessment(), datum=date(2026, 11, 5))

    merke_treffernummern(conn, "2026-11-05-2", {"a-1": 2, "a-2": 1})

    zeilen = conn.execute("SELECT id, report, nummer FROM gesehene_anzeigen ORDER BY id").fetchall()
    assert zeilen == [("a-1", "2026-11-05-2", 2), ("a-2", "2026-11-05-2", 1)]


def _alte_datenbank(pfad: Path) -> None:
    alt = sqlite3.connect(pfad)
    alt.execute(
        "CREATE TABLE gesehene_anzeigen (id TEXT PRIMARY KEY, titel TEXT NOT NULL, firma TEXT, "
        "link TEXT NOT NULL, score INTEGER NOT NULL, datum TEXT NOT NULL)"
    )
    alt.execute(
        "INSERT INTO gesehene_anzeigen VALUES ('alt-1', 'Titel', 'Firma', 'link', 3, '2026-11-06')"
    )
    alt.commit()
    alt.close()


def test_connect_migriert_alte_datenbank_ohne_datenverlust(tmp_path: Path) -> None:
    db_pfad = tmp_path / "alt.db"
    _alte_datenbank(db_pfad)

    verbindung = connect(db_pfad)
    try:
        zeile = verbindung.execute(
            "SELECT id, score, datum, report, nummer, beschreibung_hash, bewertung "
            "FROM gesehene_anzeigen"
        ).fetchone()
        assert zeile == ("alt-1", 3, "2026-11-06", None, None, None, None)
        assert is_new(verbindung, "alt-1") is False
    finally:
        verbindung.close()


def test_connect_ist_bei_wiederholtem_oeffnen_stabil(tmp_path: Path) -> None:
    db_pfad = tmp_path / "alt.db"
    _alte_datenbank(db_pfad)

    connect(db_pfad).close()
    connect(db_pfad).close()


def test_connect_erstellt_tabelle_in_datei(tmp_path: Path) -> None:
    db_pfad = tmp_path / "jobagent.db"

    verbindung = connect(db_pfad)
    try:
        assert is_new(verbindung, "irgendeine-id") is True
    finally:
        verbindung.close()

    assert db_pfad.exists()


def test_multiple_job_ads_are_tracked_independently(conn) -> None:
    mark_seen(conn, _example_job_ad("a-1"), assessment=_assessment(5), datum=date(2026, 11, 5))

    assert is_new(conn, "a-1") is False
    assert is_new(conn, "a-2") is True
