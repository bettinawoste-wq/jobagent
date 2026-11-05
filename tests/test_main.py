"""Tests fuer main.py: Ablauf fetch -> dedupe -> score -> report, alles gemockt."""

from pathlib import Path

import pytest

from jobagent import fetch, main, score
from jobagent.fetch import Anzeige
from jobagent.score import Bewertung

_KONFIG = """
wo = "München"
umkreis = 30
veroeffentlichtseit = 1
was = ["Softwareentwickler"]
"""

_PROFIL = "# Suchprofil\nPython, München, Hybrid bevorzugt."


@pytest.fixture(autouse=True)
def _keine_echten_arbeitnow_aufrufe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "search_arbeitnow", lambda *a, **kw: [])


@pytest.fixture
def projekt(tmp_path: Path) -> dict[str, Path]:
    konfig_pfad = tmp_path / "config.toml"
    konfig_pfad.write_text(_KONFIG, encoding="utf-8")
    profil_pfad = tmp_path / "profile.md"
    profil_pfad.write_text(_PROFIL, encoding="utf-8")
    return {
        "konfig_pfad": konfig_pfad,
        "profil_pfad": profil_pfad,
        "db_pfad": tmp_path / "jobagent.db",
        "ausgabe_verzeichnis": tmp_path / "output",
    }


def _anzeige(id_: str) -> Anzeige:
    return Anzeige(
        id=id_,
        titel=f"Stelle {id_}",
        firma="Beispiel GmbH",
        ort="München",
        link=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{id_}",
    )


def _bewertung() -> Bewertung:
    return Bewertung(score=4, passt=["Python"], passt_nicht=[], luecken=[], kurzfazit="Passt.")


def _score_und_merke(aufrufe: list[str]):
    def score_anzeige(anzeige: Anzeige, profil: str) -> Bewertung:
        aufrufe.append(anzeige.id)
        return _bewertung()

    return score_anzeige


def test_main_schreibt_report_fuer_neue_treffer(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: [_anzeige("a-1")])
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())

    pfad = main.main(**projekt)

    inhalt = pfad.read_text(encoding="utf-8")
    assert "Stelle a-1" in inhalt
    assert "4/5" in inhalt


def test_main_ueberspringt_bereits_gesehene_anzeigen(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    aufrufe = []
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: [_anzeige("a-1")])
    monkeypatch.setattr(score, "score_anzeige", _score_und_merke(aufrufe))

    main.main(**projekt)
    pfad_zweiter_lauf = main.main(**projekt)

    assert aufrufe == ["a-1"]
    assert "Keine neuen Treffer" in pfad_zweiter_lauf.read_text(encoding="utf-8")


def test_main_ohne_suchtreffer_schreibt_notiz(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: [])
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())

    pfad = main.main(**projekt)

    assert "Keine neuen Treffer" in pfad.read_text(encoding="utf-8")


def test_main_markiert_nicht_als_gesehen_wenn_bewertung_fehlschlaegt(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: [_anzeige("a-1")])
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: None)

    erster_lauf = main.main(**projekt)
    assert "Keine neuen Treffer" in erster_lauf.read_text(encoding="utf-8")

    aufrufe = []
    monkeypatch.setattr(score, "score_anzeige", _score_und_merke(aufrufe))
    zweiter_lauf = main.main(**projekt)

    assert aufrufe == ["a-1"]
    assert "Stelle a-1" in zweiter_lauf.read_text(encoding="utf-8")


def test_main_dedupliziert_treffer_ueber_mehrere_suchbegriffe(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    projekt["konfig_pfad"].write_text(
        'wo = "München"\numkreis = 30\nveroeffentlichtseit = 1\n'
        'was = ["Softwareentwickler", "IT Consultant"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: [_anzeige("a-1")])
    aufrufe = []
    monkeypatch.setattr(score, "score_anzeige", _score_und_merke(aufrufe))

    main.main(**projekt)

    assert aufrufe == ["a-1"]


def test_main_kombiniert_treffer_aus_beiden_quellen(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    arbeitnow_anzeige = Anzeige(
        id="arbeitnow:full-stack-entwickler-100",
        titel="Full-Stack-Entwickler (m/w/d)",
        firma="Arbeitnow-Firma",
        ort="Berlin",
        link="https://www.arbeitnow.com/jobs/companies/arbeitnow-firma/full-stack-entwickler-100",
    )
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: [_anzeige("a-1")])
    monkeypatch.setattr(fetch, "search_arbeitnow", lambda *a, **kw: [arbeitnow_anzeige])
    aufrufe = []
    monkeypatch.setattr(score, "score_anzeige", _score_und_merke(aufrufe))

    pfad = main.main(**projekt)

    inhalt = pfad.read_text(encoding="utf-8")
    assert "Stelle a-1" in inhalt
    assert "Full-Stack-Entwickler (m/w/d)" in inhalt
    assert sorted(aufrufe) == ["a-1", "arbeitnow:full-stack-entwickler-100"]
