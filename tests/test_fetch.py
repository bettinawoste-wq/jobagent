"""Tests fuer fetch.py, ausschliesslich gegen gespeicherte Beispielantworten."""

import base64
import json
from pathlib import Path

import httpx
import pytest

from jobagent.fetch import Anzeige, search

_FIXTURES = Path(__file__).parent / "fixtures"
JOBSUCHE_FIXTURE = json.loads((_FIXTURES / "jobsuche_response.json").read_text(encoding="utf-8"))
JOBDETAILS_FIXTURE = json.loads(
    (_FIXTURES / "jobdetails_response.json").read_text(encoding="utf-8")
)

_SEARCH_PATH = "/jobboerse/jobsuche-service/pc/v6/jobs"
_DETAILS_PREFIX = "/jobboerse/jobsuche-service/pc/v4/jobdetails/"


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
            titel="Softwareentwickler/in (m/w/d)",
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
        return httpx.Response(200, json={"stellenangebote": []})

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
