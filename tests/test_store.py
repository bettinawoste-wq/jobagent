"""Tests fuer store.py mit temporaerer Datenbank."""

import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from jobagent.fetch import Anzeige
from jobagent.score import Bewertung
from jobagent.store import connect, is_new, mark_seen, merke_treffernummern


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


def _bewertung(score: int = 4) -> Bewertung:
    return Bewertung(
        score=score,
        passt=["Python"],
        passt_nicht=["Reisen"],
        luecken=["Kubernetes"],
        kurzfazit="Passt gut für München.",
    )


def _hash_von(conn, anzeige_id: str) -> str | None:
    return conn.execute(
        "SELECT beschreibung_hash FROM gesehene_anzeigen WHERE id = ?", (anzeige_id,)
    ).fetchone()[0]


def test_is_new_true_fuer_unbekannte_id(conn) -> None:
    assert is_new(conn, "unbekannte-id") is True


def test_mark_seen_macht_is_new_false(conn) -> None:
    anzeige = _beispiel_anzeige()

    mark_seen(conn, anzeige, bewertung=_bewertung(4), datum=date(2026, 11, 5))

    assert is_new(conn, anzeige.id) is False


def test_mark_seen_speichert_korrekte_werte(conn) -> None:
    anzeige = _beispiel_anzeige()

    mark_seen(conn, anzeige, bewertung=_bewertung(4), datum=date(2026, 11, 5))

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
    mark_seen(conn, _beispiel_anzeige(), bewertung=_bewertung(4), datum=date(2026, 11, 5))

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


def test_mark_seen_speichert_bewertungsdetails(conn) -> None:
    anzeige = _beispiel_anzeige()

    mark_seen(conn, anzeige, bewertung=_bewertung(), datum=date(2026, 11, 5))

    roh = conn.execute(
        "SELECT bewertung FROM gesehene_anzeigen WHERE id = ?", (anzeige.id,)
    ).fetchone()[0]
    assert json.loads(roh) == {
        "passt": ["Python"],
        "passt_nicht": ["Reisen"],
        "luecken": ["Kubernetes"],
        "kurzfazit": "Passt gut für München.",
    }


def test_hash_ignoriert_unterschiede_im_leerraum(conn) -> None:
    einzeilig = replace(_beispiel_anzeige("a-1"), beschreibung="Python in München")
    umbrochen = replace(_beispiel_anzeige("a-2"), beschreibung="  Python\n\nin   München ")

    mark_seen(conn, einzeilig, bewertung=_bewertung(), datum=date(2026, 11, 5))
    mark_seen(conn, umbrochen, bewertung=_bewertung(), datum=date(2026, 11, 5))

    assert _hash_von(conn, "a-1") == _hash_von(conn, "a-2")


def test_hash_unterscheidet_abweichenden_text(conn) -> None:
    alt = replace(_beispiel_anzeige("a-1"), beschreibung="Python in München")
    neu = replace(_beispiel_anzeige("a-2"), beschreibung="Python in Berlin")

    mark_seen(conn, alt, bewertung=_bewertung(), datum=date(2026, 11, 5))
    mark_seen(conn, neu, bewertung=_bewertung(), datum=date(2026, 11, 5))

    assert _hash_von(conn, "a-1") != _hash_von(conn, "a-2")


@pytest.mark.parametrize("beschreibung", [None, "", "  \n "])
def test_kein_hash_ohne_beschreibung(conn, beschreibung: str | None) -> None:
    anzeige = replace(_beispiel_anzeige(), beschreibung=beschreibung)

    mark_seen(conn, anzeige, bewertung=_bewertung(), datum=date(2026, 11, 5))

    assert _hash_von(conn, anzeige.id) is None


def test_merke_treffernummern_ordnet_report_und_nummer_zu(conn) -> None:
    mark_seen(conn, _beispiel_anzeige("a-1"), bewertung=_bewertung(), datum=date(2026, 11, 5))
    mark_seen(conn, _beispiel_anzeige("a-2"), bewertung=_bewertung(), datum=date(2026, 11, 5))

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


def test_mehrere_anzeigen_werden_unabhaengig_verfolgt(conn) -> None:
    mark_seen(conn, _beispiel_anzeige("a-1"), bewertung=_bewertung(5), datum=date(2026, 11, 5))

    assert is_new(conn, "a-1") is False
    assert is_new(conn, "a-2") is True
