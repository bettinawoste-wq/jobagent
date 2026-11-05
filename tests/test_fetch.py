"""Tests fuer fetch.py, ausschliesslich gegen gespeicherte Beispielantworten."""

import base64
import json
import time
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from jobagent.fetch import (
    Anzeige,
    search,
    search_arbeitnow,
    search_greenhouse,
    search_lever,
    search_watchlist,
)

_FIXTURES = Path(__file__).parent / "fixtures"
JOBSUCHE_FIXTURE = json.loads((_FIXTURES / "jobsuche_response.json").read_text(encoding="utf-8"))
JOBDETAILS_FIXTURE = json.loads(
    (_FIXTURES / "jobdetails_response.json").read_text(encoding="utf-8")
)
ARBEITNOW_FIXTURE = json.loads((_FIXTURES / "arbeitnow_response.json").read_text(encoding="utf-8"))
ARBEITNOW_SEITE1 = json.loads(
    (_FIXTURES / "arbeitnow_response_seite1.json").read_text(encoding="utf-8")
)
ARBEITNOW_SEITE2 = json.loads(
    (_FIXTURES / "arbeitnow_response_seite2.json").read_text(encoding="utf-8")
)

_SEARCH_PATH = "/jobboerse/jobsuche-service/pc/v6/jobs"
_DETAILS_PREFIX = "/jobboerse/jobsuche-service/pc/v4/jobdetails/"


def _vor_tagen(tage: float) -> float:
    return time.time() - tage * 86400


def _mit_alter(daten: dict, alter_in_tagen: dict[int, float]) -> dict:
    """Kopiert die Fixture und setzt created_at je Eintrag relativ zu jetzt."""
    kopie = deepcopy(daten)
    for index, tage in alter_in_tagen.items():
        kopie["data"][index]["created_at"] = _vor_tagen(tage)
    return kopie


def _transport(handler):
    return httpx.MockTransport(handler)


def _erfolgreicher_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == _SEARCH_PATH:
        return httpx.Response(200, json=JOBSUCHE_FIXTURE)
    if request.url.path.startswith(_DETAILS_PREFIX):
        code = request.url.path.removeprefix(_DETAILS_PREFIX)
        refnr = base64.b64decode(code).decode()
        return httpx.Response(200, json=JOBDETAILS_FIXTURE[refnr])
    raise AssertionError(f"Unerwartete URL: {request.url}")


def test_search_mapt_antwort_auf_anzeigen_inklusive_details() -> None:
    ergebnis = search(
        "Softwareentwicklerin",
        wo="München",
        umkreis=30,
        veroeffentlichtseit=7,
        transport=_transport(_erfolgreicher_handler),
    )

    assert ergebnis == [
        Anzeige(
            id="10001-1003353506-S",
            titel="Softwareentwickler/in Linux (m/w/d)",
            firma="Beispiel GmbH",
            ort="München",
            link="https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003353506-S",
            beschreibung=(
                "Wir suchen eine Softwareentwicklerin fuer unser Backend-Team in "
                "Python und C++. Aufgaben: API-Design, CI/CD, Code-Reviews. "
                "Erfahrung mit Cloud-Migration von Vorteil."
            ),
        ),
        Anzeige(
            id="10001-1003353507-S",
            titel="IT Consultant (m/w/d)",
            firma="Consulting AG",
            ort="Garching",
            link="https://www.consulting-ag.example/karriere/it-consultant",
            beschreibung=None,
        ),
    ]


def test_search_sendet_erwartete_suchparameter_und_header() -> None:
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _erfolgreicher_handler(request)

    search(
        "Softwareentwicklerin",
        wo="München",
        umkreis=30,
        veroeffentlichtseit=7,
        transport=_transport(handler),
    )

    suchanfrage = next(r for r in captured_requests if r.url.path == _SEARCH_PATH)
    params = suchanfrage.url.params
    assert params["was"] == "Softwareentwicklerin"
    assert params["wo"] == "München"
    assert params["umkreis"] == "30"
    assert params["veroeffentlichtseit"] == "7"
    assert suchanfrage.headers["X-API-Key"] == "jobboerse-jobsuche"

    detailanfragen = [r for r in captured_requests if r.url.path.startswith(_DETAILS_PREFIX)]
    assert len(detailanfragen) == 2
    assert all(r.headers["X-API-Key"] == "jobboerse-jobsuche" for r in detailanfragen)


def test_search_ohne_treffer_ruft_keine_details_ab() -> None:
    aufrufe = []

    def handler(request: httpx.Request) -> httpx.Response:
        aufrufe.append(request)
        return httpx.Response(200, json={"ergebnisliste": []})

    ergebnis = search("Data Science", transport=_transport(handler))

    assert ergebnis == []
    assert len(aufrufe) == 1


def test_search_gibt_leere_liste_bei_http_fehler(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with caplog.at_level("ERROR"):
        ergebnis = search("Data Science", transport=_transport(handler))

    assert ergebnis == []
    assert "fehlgeschlagen" in caplog.text


def test_search_gibt_leere_liste_bei_netzwerkfehler(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("keine Verbindung", request=request)

    with caplog.at_level("ERROR"):
        ergebnis = search("Data Science", transport=_transport(handler))

    assert ergebnis == []
    assert "fehlgeschlagen" in caplog.text


def test_search_gibt_leere_liste_bei_ungueltigem_json(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"nicht json")

    with caplog.at_level("ERROR"):
        ergebnis = search("Data Science", transport=_transport(handler))

    assert ergebnis == []
    assert "JSON" in caplog.text


def test_search_setzt_beschreibung_auf_none_bei_detailfehler(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _SEARCH_PATH:
            return httpx.Response(200, json=JOBSUCHE_FIXTURE)
        if request.url.path.startswith(_DETAILS_PREFIX):
            return httpx.Response(500)
        raise AssertionError(f"Unerwartete URL: {request.url}")

    with caplog.at_level("ERROR"):
        ergebnis = search("Softwareentwicklerin", transport=_transport(handler))

    assert len(ergebnis) == 2
    assert all(anzeige.beschreibung is None for anzeige in ergebnis)
    assert ergebnis[0].id == "10001-1003353506-S"
    assert "Jobdetails" in caplog.text


def test_search_arbeitnow_filtert_nach_titel_und_ort() -> None:
    # "(m/w/d)" + "Berlin" trifft nur Eintrag 0: Eintrag 1 ist "(m/w/d)" aber
    # in Muenchen, Eintrag 2 ist in Berlin aber ohne "(m/w/d)" im Titel.
    daten = _mit_alter(ARBEITNOW_FIXTURE, {0: 1, 1: 1})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=daten)

    ergebnis = search_arbeitnow(
        "(m/w/d)", wo="Berlin", veroeffentlichtseit=14, transport=_transport(handler)
    )

    assert [a.titel for a in ergebnis] == ["Full-Stack-Entwickler (m/w/d)"]
    assert ergebnis[0].id == "arbeitnow:full-stack-entwickler-berlin-100001"
    assert ergebnis[0].firma == "Beispiel Tech GmbH"
    assert ergebnis[0].ort == "Berlin"


def test_search_arbeitnow_bereinigt_html_in_beschreibung() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ARBEITNOW_FIXTURE)

    ergebnis = search_arbeitnow("(m/w/d)", wo="Berlin", transport=_transport(handler))

    assert [a.titel for a in ergebnis] == ["Full-Stack-Entwickler (m/w/d)"]
    assert ergebnis[0].beschreibung == "Wir suchen Python & JavaScript Erfahrung."


def test_search_arbeitnow_stoppt_bei_zu_alten_eintraegen_ohne_naechste_seite() -> None:
    seite1_alt = deepcopy(ARBEITNOW_SEITE1)
    seite1_alt["data"][0]["created_at"] = _vor_tagen(60)
    aufrufe = []

    def handler(request: httpx.Request) -> httpx.Response:
        aufrufe.append(request)
        return httpx.Response(200, json=seite1_alt)

    ergebnis = search_arbeitnow(
        "Data Scientist", veroeffentlichtseit=7, transport=_transport(handler)
    )

    assert ergebnis == []
    assert len(aufrufe) == 1


def test_search_arbeitnow_folgt_naechster_seite_innerhalb_des_zeitfensters() -> None:
    seite1 = _mit_alter(ARBEITNOW_SEITE1, {0: 1})
    seite2 = _mit_alter(ARBEITNOW_SEITE2, {0: 2})
    aufrufe = []

    def handler(request: httpx.Request) -> httpx.Response:
        aufrufe.append(request)
        return httpx.Response(200, json=seite1 if len(aufrufe) == 1 else seite2)

    ergebnis = search_arbeitnow(
        "Data Scientist", veroeffentlichtseit=14, transport=_transport(handler)
    )

    assert len(aufrufe) == 2
    assert {a.id for a in ergebnis} == {
        "arbeitnow:data-scientist-berlin-200001",
        "arbeitnow:data-scientist-hamburg-200002",
    }


def test_search_arbeitnow_gibt_bisherige_treffer_bei_http_fehler_auf_folgeseite(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seite1 = _mit_alter(ARBEITNOW_SEITE1, {0: 1})
    aufrufe = []

    def handler(request: httpx.Request) -> httpx.Response:
        aufrufe.append(request)
        if len(aufrufe) == 1:
            return httpx.Response(200, json=seite1)
        return httpx.Response(500)

    with caplog.at_level("ERROR"):
        ergebnis = search_arbeitnow(
            "Data Scientist", veroeffentlichtseit=14, transport=_transport(handler)
        )

    assert [a.id for a in ergebnis] == ["arbeitnow:data-scientist-berlin-200001"]
    assert "fehlgeschlagen" in caplog.text


def test_search_arbeitnow_gibt_leere_liste_bei_ungueltigem_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"nicht json")

    with caplog.at_level("ERROR"):
        ergebnis = search_arbeitnow("Data Scientist", transport=_transport(handler))

    assert ergebnis == []
    assert "JSON" in caplog.text


GREENHOUSE_JOBS_FIXTURE = json.loads(
    (_FIXTURES / "greenhouse_jobs_response.json").read_text(encoding="utf-8")
)
GREENHOUSE_DETAIL_FIXTURE = json.loads(
    (_FIXTURES / "greenhouse_job_detail_response.json").read_text(encoding="utf-8")
)
LEVER_POSTINGS_FIXTURE = json.loads(
    (_FIXTURES / "lever_postings_response.json").read_text(encoding="utf-8")
)

_GREENHOUSE_JOBS_PATH = "/v1/boards/beispiel/jobs"
_GREENHOUSE_DETAIL_PATH = "/v1/boards/beispiel/jobs/1001"
_LEVER_PATH = "/v0/postings/beispiel"


def _greenhouse_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == _GREENHOUSE_JOBS_PATH:
        return httpx.Response(200, json=GREENHOUSE_JOBS_FIXTURE)
    if request.url.path == _GREENHOUSE_DETAIL_PATH:
        return httpx.Response(200, json=GREENHOUSE_DETAIL_FIXTURE)
    raise AssertionError(f"Unerwartete URL: {request.url}")


def test_search_greenhouse_filtert_nach_titel_und_holt_beschreibung() -> None:

    ergebnis = search_greenhouse(
        "beispiel", "Full-Stack", transport=_transport(_greenhouse_handler)
    )

    assert len(ergebnis) == 1
    treffer = ergebnis[0]
    assert treffer.id == "greenhouse:beispiel:1001"
    assert treffer.titel == "Full-Stack-Entwickler (m/w/d)"
    assert treffer.firma == "Beispiel GmbH"
    assert treffer.ort == "München, Deutschland"
    assert treffer.link == "https://job-boards.greenhouse.io/beispiel/jobs/1001"
    assert treffer.beschreibung == "Wir suchen Python & JavaScript Erfahrung."


def test_search_greenhouse_ruft_keinen_detail_fuer_nicht_passende_jobs() -> None:

    aufrufe = []

    def handler(request: httpx.Request) -> httpx.Response:
        aufrufe.append(request.url.path)
        return _greenhouse_handler(request)

    search_greenhouse("beispiel", "Marketing", transport=_transport(handler))

    assert _GREENHOUSE_DETAIL_PATH not in aufrufe


def test_search_greenhouse_gibt_leere_liste_bei_http_fehler(
    caplog: pytest.LogCaptureFixture,
) -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with caplog.at_level("ERROR"):
        ergebnis = search_greenhouse("unbekannt", "Full-Stack", transport=_transport(handler))

    assert ergebnis == []
    assert "fehlgeschlagen" in caplog.text


def test_search_lever_filtert_nach_titel_und_nutzt_plaintext_beschreibung() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == _LEVER_PATH
        return httpx.Response(200, json=LEVER_POSTINGS_FIXTURE)

    ergebnis = search_lever(
        "beispiel", "Beispiel GmbH", "Full-Stack", transport=_transport(handler)
    )

    assert len(ergebnis) == 1
    treffer = ergebnis[0]
    assert treffer.id == "lever:beispiel:posting-1"
    assert treffer.titel == "Full-Stack-Entwickler (m/w/d)"
    assert treffer.firma == "Beispiel GmbH"
    assert treffer.ort == "München"
    assert treffer.link == "https://jobs.lever.co/beispiel/posting-1"
    assert treffer.beschreibung == "Wir suchen Python Erfahrung."


def test_search_lever_gibt_leere_liste_bei_ungueltigem_json(
    caplog: pytest.LogCaptureFixture,
) -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"nicht json")

    with caplog.at_level("ERROR"):
        ergebnis = search_lever(
            "beispiel", "Beispiel GmbH", "Full-Stack", transport=_transport(handler)
        )

    assert ergebnis == []
    assert "JSON" in caplog.text


def test_search_watchlist_kombiniert_greenhouse_und_lever() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boards-api.greenhouse.io":
            return _greenhouse_handler(request)
        if request.url.host == "api.lever.co":
            assert request.url.path == _LEVER_PATH
            return httpx.Response(200, json=LEVER_POSTINGS_FIXTURE)
        raise AssertionError(f"Unerwartete URL: {request.url}")

    firmen = [
        {"name": "Beispiel GmbH (GH)", "ats": "greenhouse", "slug": "beispiel"},
        {"name": "Beispiel GmbH", "ats": "lever", "slug": "beispiel"},
    ]

    ergebnis = search_watchlist(firmen, "Full-Stack", transport=_transport(handler))

    assert {a.id for a in ergebnis} == {"greenhouse:beispiel:1001", "lever:beispiel:posting-1"}


def test_search_watchlist_ueberspringt_firma_mit_unbekanntem_ats(
    caplog: pytest.LogCaptureFixture,
) -> None:

    firmen = [{"name": "Mysteriy AG", "ats": "mysteryats", "slug": "mysteriy"}]

    with caplog.at_level("ERROR"):
        ergebnis = search_watchlist(firmen, "Full-Stack")

    assert ergebnis == []
    assert "Unbekannter ats-Typ" in caplog.text


def test_search_watchlist_isoliert_fehler_einer_firma() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        if "kaputt" in request.url.path:
            return httpx.Response(500)
        return _greenhouse_handler(request)

    firmen = [
        {"name": "Kaputte Firma", "ats": "greenhouse", "slug": "kaputt"},
        {"name": "Beispiel GmbH", "ats": "greenhouse", "slug": "beispiel"},
    ]

    ergebnis = search_watchlist(firmen, "Full-Stack", transport=_transport(handler))

    assert [a.id for a in ergebnis] == ["greenhouse:beispiel:1001"]
