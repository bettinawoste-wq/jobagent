"""Tests fuer main.py: Ablauf fetch -> dedupe -> score -> report, alles gemockt."""

from dataclasses import replace
from pathlib import Path

import pytest

from jobagent import feedback, fetch, main, score, store
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
def _keine_echten_zweit_und_drittquellen_aufrufe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "search_arbeitnow", lambda *a, **kw: fetch.Suchergebnis([]))
    monkeypatch.setattr(fetch, "search_watchlist", lambda *a, **kw: fetch.Suchergebnis([]))


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
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")]))
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())

    pfad = main.main(**projekt)

    inhalt = pfad.read_text(encoding="utf-8")
    assert "Stelle a-1" in inhalt
    assert "4/5" in inhalt


def test_main_schreibt_quellenstatus_in_den_report(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")], []))
    monkeypatch.setattr(
        fetch, "search_arbeitnow", lambda *a, **kw: fetch.Suchergebnis([], ["x: HTTP 500"])
    )
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "- Bundesagentur für Arbeit: 1 Anzeige\n" in inhalt
    assert "- Arbeitnow: FEHLER, 0 Anzeigen (x: HTTP 500)" in inhalt
    assert "Firmen-Watchlist" not in inhalt


def test_main_zaehlt_anzeigen_ueber_suchbegriffe_einmal_und_kuerzt_gleiche_fehler(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    projekt["konfig_pfad"].write_text('was = ["A", "B"]\n', encoding="utf-8")
    monkeypatch.setattr(
        fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")], ["kaputt"])
    )
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "- Bundesagentur für Arbeit: FEHLER, 1 Anzeige (kaputt)\n" in inhalt


def test_main_ueberlebt_unerwarteten_fehler_einer_quelle(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def kaputt(*args, **kwargs):
        raise KeyError("referenznummer")

    monkeypatch.setattr(fetch, "search", kaputt)
    monkeypatch.setattr(
        fetch, "search_arbeitnow", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")], [])
    )
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "Bundesagentur für Arbeit: FEHLER" in inhalt
    assert "unerwarteter Fehler" in inhalt
    assert "Stelle a-1" in inhalt


def test_main_nimmt_mindest_score_aus_der_konfiguration(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    projekt["konfig_pfad"].write_text('was = ["A"]\nmindest_score = 5\n', encoding="utf-8")
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")], []))
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "## Weitere Treffer (Score unter 5)" in inhalt
    assert "- **1.** Stelle a-1" in inhalt


def test_main_nutzt_standard_mindest_score_ohne_konfiguration(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")], []))
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: replace(_bewertung(), score=2))

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "## Weitere Treffer (Score unter 3)" in inhalt


def test_main_merkt_sich_report_und_treffernummer(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    scores = {"a-1": 2, "a-2": 5}

    def bewerte(anzeige: Anzeige, profil: str) -> Bewertung:
        return replace(_bewertung(), score=scores[anzeige.id])

    monkeypatch.setattr(
        fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1"), _anzeige("a-2")])
    )
    monkeypatch.setattr(score, "score_anzeige", bewerte)

    pfad = main.main(**projekt)

    conn = store.connect(projekt["db_pfad"])
    try:
        zeilen = conn.execute(
            "SELECT id, report, nummer FROM gesehene_anzeigen ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert zeilen == [("a-1", pfad.stem, 2), ("a-2", pfad.stem, 1)]


def test_main_ueberspringt_bereits_gesehene_anzeigen(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    aufrufe = []
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")]))
    monkeypatch.setattr(score, "score_anzeige", _score_und_merke(aufrufe))

    main.main(**projekt)
    pfad_zweiter_lauf = main.main(**projekt)

    assert aufrufe == ["a-1"]
    assert "Keine neuen Treffer" in pfad_zweiter_lauf.read_text(encoding="utf-8")


def test_main_ohne_suchtreffer_schreibt_notiz(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([]))
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())

    pfad = main.main(**projekt)

    assert "Keine neuen Treffer" in pfad.read_text(encoding="utf-8")


def test_main_markiert_nicht_als_gesehen_wenn_bewertung_fehlschlaegt(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")]))
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
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")]))
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
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_anzeige("a-1")]))
    monkeypatch.setattr(
        fetch, "search_arbeitnow", lambda *a, **kw: fetch.Suchergebnis([arbeitnow_anzeige])
    )
    aufrufe = []
    monkeypatch.setattr(score, "score_anzeige", _score_und_merke(aufrufe))

    pfad = main.main(**projekt)

    inhalt = pfad.read_text(encoding="utf-8")
    assert "Stelle a-1" in inhalt
    assert "Full-Stack-Entwickler (m/w/d)" in inhalt
    assert sorted(aufrufe) == ["a-1", "arbeitnow:full-stack-entwickler-100"]


def test_main_bindet_watchlist_firmen_aus_config_ein(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    projekt["konfig_pfad"].write_text(
        'wo = "München"\numkreis = 30\nveroeffentlichtseit = 1\n'
        'was = ["Softwareentwickler"]\n\n'
        '[[firmen]]\nname = "GitLab"\nats = "greenhouse"\nslug = "gitlab"\n',
        encoding="utf-8",
    )
    watchlist_anzeige = Anzeige(
        id="greenhouse:gitlab:999",
        titel="Full-Stack-Entwickler (m/w/d)",
        firma="GitLab",
        ort="Remote",
        link="https://job-boards.greenhouse.io/gitlab/jobs/999",
    )
    erhaltene_firmen = []

    def fake_search_watchlist(firmen, was, **kw):
        erhaltene_firmen.append(firmen)
        return fetch.Suchergebnis([watchlist_anzeige])

    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([]))
    monkeypatch.setattr(fetch, "search_watchlist", fake_search_watchlist)
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())

    pfad = main.main(**projekt)

    assert erhaltene_firmen == [[{"name": "GitLab", "ats": "greenhouse", "slug": "gitlab"}]]
    assert "Full-Stack-Entwickler (m/w/d)" in pfad.read_text(encoding="utf-8")


def _stelle(id_: str, beschreibung: str | None = "Text", titel: str = "Data Engineer") -> Anzeige:
    return Anzeige(
        id=id_,
        titel=titel,
        firma="Beispiel GmbH",
        ort="München",
        link=f"https://x.example/{id_}",
        beschreibung=beschreibung,
    )


def _lauf_findet(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch, anzeige: Anzeige
) -> tuple[Path, str]:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([anzeige]))
    monkeypatch.setattr(score, "score_anzeige", lambda *a, **kw: _bewertung())
    pfad = main.main(**projekt)
    return pfad, pfad.read_text(encoding="utf-8")


def _manuell(projekt: dict[str, Path], aktion: str = "beworben", titel: str = "Data Engineer"):
    argumente = [aktion, "--firma", "Beispiel", "--titel", titel]
    assert feedback.main(argumente, db_pfad=projekt["db_pfad"]) == 0


def _bewerbung_auf_erste_anzeige(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch, beschreibung: str | None
) -> None:
    pfad, _ = _lauf_findet(projekt, monkeypatch, _stelle("alt", beschreibung))
    assert feedback.main([pfad.stem, "1", "beworben"], db_pfad=projekt["db_pfad"]) == 0


def test_main_verschiebt_bereits_beworbene_stelle_in_eigenen_block(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)

    _, inhalt = _lauf_findet(projekt, monkeypatch, _stelle("neu"))

    assert "## Bereits beworben" in inhalt
    assert "Data Engineer (Beispiel GmbH, München) – Score 4/5 – beworben, beworben am" in inhalt
    assert "## 1. Data Engineer" not in inhalt


def test_main_erkennt_stelle_trotz_firmenname_im_titel(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)
    anzeige = _stelle("neu", titel="Beispiel GmbH: Data Engineer (w/m/x)")

    _, inhalt = _lauf_findet(projekt, monkeypatch, anzeige)

    assert "## Bereits beworben" in inhalt


def test_main_zeigt_status_der_bewerbung(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)
    _manuell(projekt, "absage")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _stelle("neu"))

    assert "– absage, beworben am" in inhalt


def test_main_zurueckgezogene_bewerbung_zaehlt_nicht(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)
    _manuell(projekt, "zurückgezogen")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _stelle("neu"))

    assert "Bereits beworben" not in inhalt
    assert "## 1. Data Engineer" in inhalt


def test_main_andere_stelle_bleibt_unmarkiert(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt, titel="Consultant")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _stelle("neu"))

    assert "Bereits beworben" not in inhalt


def test_main_anzeige_ohne_firma_wird_nicht_zugeordnet(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    argumente = ["beworben", "--firma", "", "--titel", "Data Engineer"]
    feedback.main(argumente, db_pfad=projekt["db_pfad"])
    ohne_firma = replace(_stelle("neu"), firma=None)

    _, inhalt = _lauf_findet(projekt, monkeypatch, ohne_firma)

    assert "Bereits beworben" not in inhalt


def test_main_meldet_identischen_text(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bewerbung_auf_erste_anzeige(projekt, monkeypatch, "Gleicher Text")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _stelle("neu", "Gleicher   Text"))

    assert "– Text identisch –" in inhalt


def test_main_meldet_textabweichung(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bewerbung_auf_erste_anzeige(projekt, monkeypatch, "Alter Text")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _stelle("neu", "Neuer Text"))

    assert "– Text weicht von deiner Bewerbung ab –" in inhalt


def test_main_manuelle_bewerbung_ist_nicht_vergleichbar(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)

    _, inhalt = _lauf_findet(projekt, monkeypatch, _stelle("neu"))

    assert "– Text nicht vergleichbar –" in inhalt


def test_main_fehlende_neue_beschreibung_ist_nicht_vergleichbar(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bewerbung_auf_erste_anzeige(projekt, monkeypatch, "Alter Text")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _stelle("neu", None))

    assert "– Text nicht vergleichbar –" in inhalt


def test_main_vergleicht_mit_letzter_bewerbung(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bewerbung_auf_erste_anzeige(projekt, monkeypatch, "Erster Text")
    pfad, _ = _lauf_findet(projekt, monkeypatch, _stelle("zwei", "Zweiter Text"))
    assert feedback.main([pfad.stem, "1", "beworben"], db_pfad=projekt["db_pfad"]) == 0

    _, inhalt = _lauf_findet(projekt, monkeypatch, _stelle("drei", "Zweiter Text"))

    assert "– Text identisch –" in inhalt
