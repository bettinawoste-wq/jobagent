"""Tests fuer report.py mit temporaerem Ausgabeverzeichnis."""

from datetime import date
from pathlib import Path

from jobagent.fetch import Anzeige
from jobagent.report import schreibe_report
from jobagent.score import Bewertung


def _anzeige(id_: str, titel: str) -> Anzeige:
    return Anzeige(
        id=id_,
        titel=titel,
        firma="Beispiel GmbH",
        ort="München",
        link=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{id_}",
    )


def _bewertung(score: int, kurzfazit: str = "Passt gut.") -> Bewertung:
    return Bewertung(
        score=score,
        passt=["Python"],
        passt_nicht=[],
        luecken=["Kubernetes"],
        kurzfazit=kurzfazit,
    )


def test_schreibe_report_sortiert_nach_score_absteigend(tmp_path: Path) -> None:
    treffer = [
        (_anzeige("a-1", "Niedrig"), _bewertung(2)),
        (_anzeige("a-2", "Hoch"), _bewertung(5)),
        (_anzeige("a-3", "Mittel"), _bewertung(3)),
    ]

    pfad = schreibe_report(treffer, date(2026, 11, 5), ausgabe_verzeichnis=tmp_path)

    assert pfad == tmp_path / "2026-11-05.md"
    inhalt = pfad.read_text(encoding="utf-8")
    pos_hoch = inhalt.index("Hoch")
    pos_mittel = inhalt.index("Mittel")
    pos_niedrig = inhalt.index("Niedrig")
    assert pos_hoch < pos_mittel < pos_niedrig


def test_schreibe_report_enthaelt_alle_pflichtfelder(tmp_path: Path) -> None:
    treffer = [(_anzeige("a-1", "Softwareentwickler"), _bewertung(4, "Gute Passung."))]

    pfad = schreibe_report(treffer, date(2026, 11, 5), ausgabe_verzeichnis=tmp_path)
    inhalt = pfad.read_text(encoding="utf-8")

    assert "Softwareentwickler" in inhalt
    assert "Beispiel GmbH" in inhalt
    assert "München" in inhalt
    assert "https://www.arbeitsagentur.de/jobsuche/jobdetail/a-1" in inhalt
    assert "4/5" in inhalt
    assert "Gute Passung." in inhalt
    assert "Python" in inhalt
    assert "Kubernetes" in inhalt


def test_schreibe_report_ohne_treffer_schreibt_notiz_statt_leerer_datei(tmp_path: Path) -> None:
    pfad = schreibe_report([], date(2026, 11, 5), ausgabe_verzeichnis=tmp_path)

    inhalt = pfad.read_text(encoding="utf-8")
    assert "Keine neuen Treffer" in inhalt
    assert len(inhalt.strip()) > 0


def test_zweiter_lauf_am_selben_tag_ueberschreibt_ersten_report_nicht(tmp_path: Path) -> None:
    tag = date(2026, 11, 5)
    erster = schreibe_report(
        [(_anzeige("a-1", "Erster Lauf"), _bewertung(4))], tag, ausgabe_verzeichnis=tmp_path
    )

    zweiter = schreibe_report(
        [(_anzeige("a-2", "Zweiter Lauf"), _bewertung(3))], tag, ausgabe_verzeichnis=tmp_path
    )

    assert erster == tmp_path / "2026-11-05.md"
    assert zweiter == tmp_path / "2026-11-05-2.md"
    assert "Erster Lauf" in erster.read_text(encoding="utf-8")
    assert "Zweiter Lauf" in zweiter.read_text(encoding="utf-8")


def test_lauf_ohne_treffer_ueberschreibt_vorhandenen_report_nicht(tmp_path: Path) -> None:
    tag = date(2026, 11, 5)
    erster = schreibe_report(
        [(_anzeige("a-1", "Erster Lauf"), _bewertung(4))], tag, ausgabe_verzeichnis=tmp_path
    )

    zweiter = schreibe_report([], tag, ausgabe_verzeichnis=tmp_path)

    assert zweiter != erster
    assert "Erster Lauf" in erster.read_text(encoding="utf-8")


def test_dritter_lauf_am_selben_tag_bekommt_naechste_laufnummer(tmp_path: Path) -> None:
    tag = date(2026, 11, 5)
    schreibe_report([], tag, ausgabe_verzeichnis=tmp_path)
    schreibe_report([], tag, ausgabe_verzeichnis=tmp_path)

    dritter = schreibe_report([], tag, ausgabe_verzeichnis=tmp_path)

    assert dritter == tmp_path / "2026-11-05-3.md"


def test_schreibe_report_erstellt_ausgabeverzeichnis(tmp_path: Path) -> None:
    ziel = tmp_path / "noch_nicht_vorhanden"

    schreibe_report([], date(2026, 11, 5), ausgabe_verzeichnis=ziel)

    assert ziel.is_dir()
