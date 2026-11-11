"""Tests fuer main.py: Ablauf fetch -> dedupe -> score -> report, alles gemockt."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from jobagent import feedback, fetch, main, score, store
from jobagent.job_ad import JobAd
from jobagent.score import Assessment

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


def _job_ad(id_: str) -> JobAd:
    return JobAd(
        id=id_,
        titel=f"Stelle {id_}",
        firma="Beispiel GmbH",
        ort="München",
        link=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{id_}",
    )


def _assessment() -> Assessment:
    return Assessment(score=4, passt=["Python"], passt_nicht=[], luecken=[], kurzfazit="Passt.")


def _score_und_merke(aufrufe: list[str]):
    def score_job_ad(job_ad: JobAd, profil: str) -> Assessment:
        aufrufe.append(job_ad.id)
        return _assessment()

    return score_job_ad


def test_main_schreibt_report_fuer_neue_treffer(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")]))
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    pfad = main.main(**projekt)

    inhalt = pfad.read_text(encoding="utf-8")
    assert "Stelle a-1" in inhalt
    assert "4/5" in inhalt


def test_main_schreibt_quellenstatus_in_den_report(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")], []))
    monkeypatch.setattr(
        fetch, "search_arbeitnow", lambda *a, **kw: fetch.Suchergebnis([], ["x: HTTP 500"])
    )
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "- Bundesagentur für Arbeit: 1 Anzeige\n" in inhalt
    assert "- Arbeitnow: FEHLER, 0 Anzeigen (x: HTTP 500)" in inhalt
    assert "Firmen-Watchlist" not in inhalt


def test_main_zaehlt_anzeigen_ueber_suchbegriffe_einmal_und_kuerzt_gleiche_fehler(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    projekt["konfig_pfad"].write_text('was = ["A", "B"]\n', encoding="utf-8")
    monkeypatch.setattr(
        fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")], ["kaputt"])
    )
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "- Bundesagentur für Arbeit: FEHLER, 1 Anzeige (kaputt)\n" in inhalt


def test_main_ueberlebt_unerwarteten_fehler_einer_quelle(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def kaputt(*args, **kwargs):
        raise KeyError("referenznummer")

    monkeypatch.setattr(fetch, "search", kaputt)
    monkeypatch.setattr(
        fetch, "search_arbeitnow", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")], [])
    )
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "Bundesagentur für Arbeit: FEHLER" in inhalt
    assert "unerwarteter Fehler" in inhalt
    assert "Stelle a-1" in inhalt


def test_main_nimmt_mindest_score_aus_der_konfiguration(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    projekt["konfig_pfad"].write_text('was = ["A"]\nmindest_score = 5\n', encoding="utf-8")
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")], []))
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "## Weitere Treffer (Score unter 5)" in inhalt
    assert "- **1.** Stelle a-1" in inhalt


def test_main_nutzt_standard_mindest_score_ohne_konfiguration(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")], []))
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: replace(_assessment(), score=2))

    inhalt = main.main(**projekt).read_text(encoding="utf-8")

    assert "## Weitere Treffer (Score unter 3)" in inhalt


def test_main_merkt_sich_report_und_treffernummer(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    scores = {"a-1": 2, "a-2": 5}

    def bewerte(job_ad: JobAd, profil: str) -> Assessment:
        return replace(_assessment(), score=scores[job_ad.id])

    monkeypatch.setattr(
        fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1"), _job_ad("a-2")])
    )
    monkeypatch.setattr(score, "score_job_ad", bewerte)

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
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")]))
    monkeypatch.setattr(score, "score_job_ad", _score_und_merke(aufrufe))

    main.main(**projekt)
    pfad_zweiter_lauf = main.main(**projekt)

    assert aufrufe == ["a-1"]
    assert "Keine neuen Treffer" in pfad_zweiter_lauf.read_text(encoding="utf-8")


def test_main_ohne_suchtreffer_schreibt_notiz(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([]))
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    pfad = main.main(**projekt)

    assert "Keine neuen Treffer" in pfad.read_text(encoding="utf-8")


def test_main_markiert_nicht_als_gesehen_wenn_bewertung_fehlschlaegt(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")]))
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: None)

    erster_lauf = main.main(**projekt)
    assert "Keine neuen Treffer" in erster_lauf.read_text(encoding="utf-8")

    aufrufe = []
    monkeypatch.setattr(score, "score_job_ad", _score_und_merke(aufrufe))
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
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")]))
    aufrufe = []
    monkeypatch.setattr(score, "score_job_ad", _score_und_merke(aufrufe))

    main.main(**projekt)

    assert aufrufe == ["a-1"]


def test_main_kombiniert_treffer_aus_beiden_quellen(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    arbeitnow_job_ad = JobAd(
        id="arbeitnow:full-stack-entwickler-100",
        titel="Full-Stack-Entwickler (m/w/d)",
        firma="Arbeitnow-Firma",
        ort="Berlin",
        link="https://www.arbeitnow.com/jobs/companies/arbeitnow-firma/full-stack-entwickler-100",
    )
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([_job_ad("a-1")]))
    monkeypatch.setattr(
        fetch, "search_arbeitnow", lambda *a, **kw: fetch.Suchergebnis([arbeitnow_job_ad])
    )
    aufrufe = []
    monkeypatch.setattr(score, "score_job_ad", _score_und_merke(aufrufe))

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
    watchlist_job_ad = JobAd(
        id="greenhouse:gitlab:999",
        titel="Full-Stack-Entwickler (m/w/d)",
        firma="GitLab",
        ort="Remote",
        link="https://job-boards.greenhouse.io/gitlab/jobs/999",
    )
    erhaltene_firmen = []

    def fake_search_watchlist(firmen, was, **kw):
        erhaltene_firmen.append(firmen)
        return fetch.Suchergebnis([watchlist_job_ad])

    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([]))
    monkeypatch.setattr(fetch, "search_watchlist", fake_search_watchlist)
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    pfad = main.main(**projekt)

    assert erhaltene_firmen == [[{"name": "GitLab", "ats": "greenhouse", "slug": "gitlab"}]]
    assert "Full-Stack-Entwickler (m/w/d)" in pfad.read_text(encoding="utf-8")


def _position_job_ad(
    id_: str, beschreibung: str | None = "Text", titel: str = "Data Engineer"
) -> JobAd:
    return JobAd(
        id=id_,
        titel=titel,
        firma="Beispiel GmbH",
        ort="München",
        link=f"https://x.example/{id_}",
        beschreibung=beschreibung,
    )


def _lauf_findet(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch, job_ad: JobAd
) -> tuple[Path, str]:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([job_ad]))
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())
    pfad = main.main(**projekt)
    return pfad, pfad.read_text(encoding="utf-8")


def _manuell(projekt: dict[str, Path], aktion: str = "beworben", titel: str = "Data Engineer"):
    argumente = [aktion, "--firma", "Beispiel", "--titel", titel]
    assert feedback.main(argumente, db_pfad=projekt["db_pfad"]) == 0


def _bewerbung_auf_erste_anzeige(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch, beschreibung: str | None
) -> None:
    pfad, _ = _lauf_findet(projekt, monkeypatch, _position_job_ad("alt", beschreibung))
    assert feedback.main([pfad.stem, "1", "beworben"], db_pfad=projekt["db_pfad"]) == 0


def test_main_verschiebt_bereits_beworbene_stelle_in_eigenen_block(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)

    _, inhalt = _lauf_findet(projekt, monkeypatch, _position_job_ad("neu"))

    assert "## Bereits beworben" in inhalt
    assert "Data Engineer (Beispiel GmbH, München) – Score 4/5 – beworben, beworben am" in inhalt
    assert "## 1. Data Engineer" not in inhalt


def test_main_erkennt_stelle_trotz_firmenname_im_titel(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)
    job_ad = _position_job_ad("neu", titel="Beispiel GmbH: Data Engineer (w/m/x)")

    _, inhalt = _lauf_findet(projekt, monkeypatch, job_ad)

    assert "## Bereits beworben" in inhalt


def test_main_zeigt_status_der_bewerbung(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)
    _manuell(projekt, "absage")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _position_job_ad("neu"))

    assert "– absage, beworben am" in inhalt


def test_main_zurueckgezogene_bewerbung_zaehlt_nicht(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)
    _manuell(projekt, "zurückgezogen")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _position_job_ad("neu"))

    assert "Bereits beworben" not in inhalt
    assert "## 1. Data Engineer" in inhalt


def test_main_andere_stelle_bleibt_unmarkiert(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt, titel="Consultant")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _position_job_ad("neu"))

    assert "Bereits beworben" not in inhalt


def test_main_anzeige_ohne_firma_wird_nicht_zugeordnet(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    argumente = ["beworben", "--firma", "", "--titel", "Data Engineer"]
    feedback.main(argumente, db_pfad=projekt["db_pfad"])
    ohne_firma = replace(_position_job_ad("neu"), firma=None)

    _, inhalt = _lauf_findet(projekt, monkeypatch, ohne_firma)

    assert "Bereits beworben" not in inhalt


def test_main_meldet_identischen_text(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bewerbung_auf_erste_anzeige(projekt, monkeypatch, "Gleicher Text")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _position_job_ad("neu", "Gleicher   Text"))

    assert "– Text identisch –" in inhalt


def test_main_meldet_textabweichung(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bewerbung_auf_erste_anzeige(projekt, monkeypatch, "Alter Text")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _position_job_ad("neu", "Neuer Text"))

    assert "– Text weicht von deiner Bewerbung ab –" in inhalt


def test_main_manuelle_bewerbung_ist_nicht_vergleichbar(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manuell(projekt)

    _, inhalt = _lauf_findet(projekt, monkeypatch, _position_job_ad("neu"))

    assert "– Text nicht vergleichbar –" in inhalt


def test_main_fehlende_neue_beschreibung_ist_nicht_vergleichbar(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bewerbung_auf_erste_anzeige(projekt, monkeypatch, "Alter Text")

    _, inhalt = _lauf_findet(projekt, monkeypatch, _position_job_ad("neu", None))

    assert "– Text nicht vergleichbar –" in inhalt


def test_main_vergleicht_mit_letzter_bewerbung(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bewerbung_auf_erste_anzeige(projekt, monkeypatch, "Erster Text")
    pfad, _ = _lauf_findet(projekt, monkeypatch, _position_job_ad("zwei", "Zweiter Text"))
    assert feedback.main([pfad.stem, "1", "beworben"], db_pfad=projekt["db_pfad"]) == 0

    _, inhalt = _lauf_findet(projekt, monkeypatch, _position_job_ad("drei", "Zweiter Text"))

    assert "– Text identisch –" in inhalt


def _beworben_vor(projekt: dict[str, Path], tagen: int, status: str = "beworben") -> None:
    am = (date.today() - timedelta(days=tagen)).isoformat()
    basis = ["--firma", "Firma X", "--titel", "Dev"]
    assert feedback.main(["beworben", *basis, "--am", am], db_pfad=projekt["db_pfad"]) == 0
    if status != "beworben":
        assert feedback.main([status, *basis], db_pfad=projekt["db_pfad"]) == 0


def _lauf_ohne_treffer(projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(fetch, "search", lambda *a, **kw: fetch.Suchergebnis([]))
    return main.main(**projekt).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("tage", "erwartet"), [(13, False), (14, True), (20, True), (28, True), (29, False)]
)
def test_main_nachfass_fenster(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tage: int, erwartet: bool
) -> None:
    _beworben_vor(projekt, tage)

    inhalt = _lauf_ohne_treffer(projekt, monkeypatch)

    assert ("## Nachfassen" in inhalt) is erwartet
    if erwartet:
        assert f"seit {tage} Tagen keine Antwort" in inhalt


@pytest.mark.parametrize("status", ["gespräch", "absage", "zusage", "zurückgezogen"])
def test_main_nachfassen_nur_bei_status_beworben(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    _beworben_vor(projekt, 20, status)

    assert "Nachfassen" not in _lauf_ohne_treffer(projekt, monkeypatch)


def test_main_nachfass_tage_aus_konfiguration(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    projekt["konfig_pfad"].write_text(
        'was = ["A"]\nnachfassen_ab_tag = 3\nnachfassen_bis_tag = 5\n', encoding="utf-8"
    )
    _beworben_vor(projekt, 4)

    assert "seit 4 Tagen keine Antwort" in _lauf_ohne_treffer(projekt, monkeypatch)


def test_main_nachfass_hinweis_aendert_den_status_nicht(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _beworben_vor(projekt, 60)

    _lauf_ohne_treffer(projekt, monkeypatch)

    conn = store.connect(projekt["db_pfad"])
    try:
        assert conn.execute("SELECT status FROM bewerbungen").fetchall() == [("beworben",)]
    finally:
        conn.close()


def _offenes_feedback(projekt: dict[str, Path], anzahl: int) -> None:
    conn = store.connect(projekt["db_pfad"])
    for nummer in range(anzahl):
        anzeige_id = f"f-{nummer}"
        store.mark_seen(conn, _job_ad(anzeige_id), _assessment(), date.today())
        store.speichere_feedback(conn, anzeige_id, 3, None, date.today())
    conn.close()


@pytest.mark.parametrize(("anzahl", "erwartet"), [(4, False), (5, True), (7, True)])
def test_main_hinweis_auf_profil_vorschlag_ab_fuenf_feedbacks(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch, anzahl: int, erwartet: bool
) -> None:
    _offenes_feedback(projekt, anzahl)

    inhalt = _lauf_ohne_treffer(projekt, monkeypatch)

    assert ("## Profil-Vorschlag" in inhalt) is erwartet
    if erwartet:
        assert f"- {anzahl} Rückmeldungen warten" in inhalt


def test_main_verarbeitetes_feedback_zaehlt_nicht(
    projekt: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _offenes_feedback(projekt, 5)
    conn = store.connect(projekt["db_pfad"])
    store.markiere_feedback_verarbeitet(conn, ["f-0"])
    conn.close()

    assert "Profil-Vorschlag" not in _lauf_ohne_treffer(projekt, monkeypatch)


def test_lauf_mit_eigenen_quellen_bewertung_und_konfiguration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def kein_netz(*args, **kwargs):
        raise AssertionError("Eingebaute Quelle darf nicht aufgerufen werden")

    def kein_modell(*args, **kwargs):
        raise AssertionError("Haiku-Bewertung darf nicht aufgerufen werden")

    monkeypatch.setattr(fetch, "search", kein_netz)
    monkeypatch.setattr(fetch, "search_arbeitnow", kein_netz)
    monkeypatch.setattr(fetch, "search_watchlist", kein_netz)
    monkeypatch.setattr(score, "score_job_ad", kein_modell)
    scores = {"a-1": 3, "a-2": 5, "b-1": 4}
    bewertet: list[str] = []

    def bewerte(job_ad: JobAd) -> Assessment:
        bewertet.append(job_ad.id)
        return replace(_assessment(), score=scores[job_ad.id])

    pfad = main.main(
        konfig_pfad=tmp_path / "fehlt.toml",
        profil_pfad=tmp_path / "fehlt.md",
        db_pfad=tmp_path / "jobagent.db",
        ausgabe_verzeichnis=tmp_path / "output",
        konfig={"was": ["Python"]},
        quellen={
            "Quelle A": lambda was: fetch.Suchergebnis([_job_ad("a-1"), _job_ad("a-2")]),
            "Quelle B": lambda was: fetch.Suchergebnis([_job_ad("b-1")], ["Python: HTTP 503"]),
        },
        bewerte=bewerte,
    )

    inhalt = pfad.read_text(encoding="utf-8")
    assert sorted(bewertet) == ["a-1", "a-2", "b-1"]
    assert "- Quelle A: 2 Anzeigen\n" in inhalt
    assert "- Quelle B: FEHLER, 1 Anzeige (Python: HTTP 503)\n" in inhalt
    assert "Bundesagentur" not in inhalt
    assert (
        inhalt.index("## 1. Stelle a-2")
        < inhalt.index("## 2. Stelle b-1")
        < inhalt.index("## 3. Stelle a-1")
    )
