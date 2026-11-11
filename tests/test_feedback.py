"""Tests fuer das Kommando feedback, gegen eine temporaere Datenbank."""

from datetime import date
from pathlib import Path

import pytest

from jobagent import feedback, store
from jobagent.job_ad import JobAd
from jobagent.position import position_key
from jobagent.score import Assessment

_HEUTE = date(2026, 11, 8)
_REPORT = "2026-11-06"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    pfad = tmp_path / "jobagent.db"
    assessment = Assessment(score=3, fits=[], misfits=[], gaps=[], summary="Geht.")
    conn = store.connect(pfad)
    for anzeige_id, titel in [("a-1", "Data Engineer (m/w/d)"), ("a-2", "Consultant")]:
        job_ad = JobAd(id=anzeige_id, title=titel, company="Beispiel GmbH", location="M", link="l")
        store.mark_seen(conn, job_ad, assessment, date(2026, 11, 6))
    store.merke_treffernummern(conn, _REPORT, {"a-1": 1, "a-2": 2})
    conn.close()
    return pfad


def _lauf(db: Path, *argumente: str) -> int:
    return feedback.main(list(argumente), db_pfad=db, heute=_HEUTE)


def _abfrage(db: Path, sql: str) -> list[tuple]:
    conn = store.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _bewerbungen(db: Path) -> list[tuple]:
    return _abfrage(db, "SELECT anzeige_id, status, beworben_am FROM bewerbungen ORDER BY id")


def _feedback(db: Path) -> list[tuple]:
    return _abfrage(db, "SELECT anzeige_id, score, grund, datum, verarbeitet FROM feedback")


def test_beworben_legt_bewerbung_an(db: Path, capsys: pytest.CaptureFixture) -> None:
    assert _lauf(db, _REPORT, "1", "beworben") == 0

    assert _bewerbungen(db) == [("a-1", "beworben", "2026-11-08")]
    assert "Data Engineer" in capsys.readouterr().out


def test_application_stores_position_key_company_and_title(db: Path) -> None:
    _lauf(db, _REPORT, "1", "beworben")

    assert _abfrage(db, "SELECT stelle, firma, titel FROM bewerbungen") == [
        (
            position_key("Beispiel GmbH", "Data Engineer"),
            "Beispiel GmbH",
            "Data Engineer (m/w/d)",
        )
    ]


def test_beworben_mit_datum(db: Path) -> None:
    _lauf(db, _REPORT, "1", "beworben", "--am", "2026-11-01")

    assert _bewerbungen(db) == [("a-1", "beworben", "2026-11-01")]


def test_erneutes_beworben_legt_keine_zweite_bewerbung_an(db: Path) -> None:
    _lauf(db, _REPORT, "1", "beworben", "--am", "2026-11-01")

    assert _lauf(db, _REPORT, "1", "beworben") == 0

    assert _bewerbungen(db) == [("a-1", "beworben", "2026-11-01")]


def test_beworben_mit_datum_korrigiert_vorhandene_bewerbung(db: Path) -> None:
    _lauf(db, _REPORT, "1", "beworben")

    _lauf(db, _REPORT, "1", "beworben", "--am", "2026-11-02")

    assert _bewerbungen(db) == [("a-1", "beworben", "2026-11-02")]


@pytest.mark.parametrize("status", ["gespräch", "absage", "zusage", "zurückgezogen"])
def test_status_ueberschreibt_und_behaelt_datum(db: Path, status: str) -> None:
    _lauf(db, _REPORT, "1", "beworben", "--am", "2026-11-01")

    assert _lauf(db, _REPORT, "1", status) == 0

    assert _bewerbungen(db) == [("a-1", status, "2026-11-01")]


def test_status_ohne_bewerbung_ist_fehler(db: Path, capsys: pytest.CaptureFixture) -> None:
    assert _lauf(db, _REPORT, "1", "absage") == 1

    assert _bewerbungen(db) == []
    assert "beworben" in capsys.readouterr().err


def test_zuruecknehmen_loescht_bewerbung(db: Path) -> None:
    _lauf(db, _REPORT, "1", "beworben")

    assert _lauf(db, _REPORT, "1", "zurücknehmen") == 0

    assert _bewerbungen(db) == []


def test_zuruecknehmen_ohne_bewerbung_ist_fehler(db: Path) -> None:
    assert _lauf(db, _REPORT, "1", "zurücknehmen") == 1


def test_unbekannter_treffer_gibt_hilfreichen_fehler(
    db: Path, capsys: pytest.CaptureFixture
) -> None:
    assert _lauf(db, _REPORT, "99", "beworben") == 1

    fehler = capsys.readouterr().err
    assert "99" in fehler
    assert "--firma" in fehler
    assert _bewerbungen(db) == []


def test_report_darf_mit_dateiendung_angegeben_werden(db: Path) -> None:
    assert _lauf(db, f"{_REPORT}.md", "2", "beworben") == 0

    assert _bewerbungen(db) == [("a-2", "beworben", "2026-11-08")]


def test_score_mit_grund(db: Path) -> None:
    assert _lauf(db, _REPORT, "2", "score", "4", "Dienstleister ist okay") == 0

    assert _feedback(db) == [("a-2", 4, "Dienstleister ist okay", "2026-11-08", 0)]


def test_score_ohne_grund(db: Path) -> None:
    assert _lauf(db, _REPORT, "2", "score", "1") == 0

    assert _feedback(db) == [("a-2", 1, None, "2026-11-08", 0)]


def test_neuer_score_ersetzt_alten_und_gilt_wieder_als_unverarbeitet(db: Path) -> None:
    _lauf(db, _REPORT, "2", "score", "1")
    conn = store.connect(db)
    conn.execute("UPDATE feedback SET verarbeitet = 1")
    conn.commit()
    conn.close()

    _lauf(db, _REPORT, "2", "score", "5", "Doch gut")

    assert _feedback(db) == [("a-2", 5, "Doch gut", "2026-11-08", 0)]


@pytest.mark.parametrize("argumente", [["0"], ["6"], ["abc"], []])
def test_ungueltiger_score_wird_abgelehnt(db: Path, argumente: list[str]) -> None:
    assert _lauf(db, _REPORT, "2", "score", *argumente) == 1

    assert _feedback(db) == []


def test_manual_application_has_no_job_ad(db: Path) -> None:
    assert _lauf(db, "beworben", "--firma", "Firma X", "--titel", "Dev (m/w/d)") == 0

    assert _abfrage(db, "SELECT stelle, firma, titel, anzeige_id, status FROM bewerbungen") == [
        (position_key("Firma X", "Dev"), "Firma X", "Dev (m/w/d)", None, "beworben")
    ]


def test_manuelle_bewerbung_mit_datum(db: Path) -> None:
    _lauf(db, "beworben", "--firma", "Firma X", "--titel", "Dev", "--am", "2026-10-01")

    assert _bewerbungen(db) == [(None, "beworben", "2026-10-01")]


def test_manueller_status_findet_bewerbung_trotz_anderer_schreibweise(db: Path) -> None:
    _lauf(db, "beworben", "--firma", "Firma X GmbH", "--titel", "Dev (m/w/d)")

    assert _lauf(db, "absage", "--firma", "firma x", "--titel", "DEV (w/m/x)") == 0

    assert _bewerbungen(db) == [(None, "absage", "2026-11-08")]


def test_manuelles_beworben_doppelt_legt_keine_zweite_an(db: Path) -> None:
    _lauf(db, "beworben", "--firma", "Firma X", "--titel", "Dev")

    assert _lauf(db, "beworben", "--firma", "Firma X", "--titel", "Dev") == 0

    assert len(_bewerbungen(db)) == 1


def test_manueller_status_ohne_bewerbung_ist_fehler(db: Path) -> None:
    assert _lauf(db, "absage", "--firma", "Firma X", "--titel", "Dev") == 1


def test_manuell_zuruecknehmen(db: Path) -> None:
    _lauf(db, "beworben", "--firma", "Firma X", "--titel", "Dev")

    assert _lauf(db, "zurücknehmen", "--firma", "Firma X", "--titel", "Dev") == 0

    assert _bewerbungen(db) == []


def test_match_can_be_new_application_for_known_position(db: Path) -> None:
    _lauf(db, "beworben", "--firma", "Beispiel GmbH", "--titel", "Data Engineer")

    _lauf(db, _REPORT, "1", "beworben")

    assert len(_bewerbungen(db)) == 2


@pytest.mark.parametrize(
    "argumente",
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
def test_falsche_aufrufe_werden_abgelehnt(db: Path, argumente: list[str]) -> None:
    with pytest.raises(SystemExit) as beendet:
        feedback.main(argumente, db_pfad=db, heute=_HEUTE)

    assert beendet.value.code == 2


def test_ungueltiges_datum_wird_abgelehnt(db: Path) -> None:
    assert _lauf(db, _REPORT, "1", "beworben", "--am", "1.11.2026") == 1

    assert _bewerbungen(db) == []


def test_datum_nur_bei_beworben_erlaubt(db: Path) -> None:
    _lauf(db, _REPORT, "1", "beworben")

    assert _lauf(db, _REPORT, "1", "absage", "--am", "2026-11-01") == 1

    assert _bewerbungen(db) == [("a-1", "beworben", "2026-11-08")]


def test_status_nimmt_keine_weiteren_argumente(db: Path) -> None:
    assert _lauf(db, _REPORT, "1", "beworben", "zu", "viel") == 1

    assert _bewerbungen(db) == []
