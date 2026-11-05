"""Tests fuer fetch.py, ausschliesslich gegen eine gespeicherte Beispielantwort."""

import json
from pathlib import Path

import httpx
import pytest

from jobagent.fetch import Anzeige, search

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "jobsuche_response.json").read_text(encoding="utf-8")
)


def _transport(handler):
    return httpx.MockTransport(handler)


def test_search_mapt_antwort_auf_anzeigen() -> None:
    captured_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["request"] = request
        return httpx.Response(200, json=FIXTURE)

    ergebnis = search(
        "Softwareentwicklerin",
        wo="München",
        umkreis=30,
        veroeffentlichtseit=7,
        transport=_transport(handler),
    )

    assert ergebnis == [
        Anzeige(
            id="10001-1003353506-S",
            titel="Softwareentwickler/in (m/w/d)",
            firma="Beispiel GmbH",
            ort="München",
            link="https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003353506-S",
        ),
        Anzeige(
            id="10001-1003353507-S",
            titel="IT Consultant (m/w/d)",
            firma="Consulting AG",
            ort="Garching",
            link="https://www.consulting-ag.example/karriere/it-consultant",
        ),
    ]

    gesendete_params = captured_request["request"].url.params
    assert gesendete_params["was"] == "Softwareentwicklerin"
    assert gesendete_params["wo"] == "München"
    assert gesendete_params["umkreis"] == "30"
    assert gesendete_params["veroeffentlichtseit"] == "7"
    assert captured_request["request"].headers["X-API-Key"] == "jobboerse-jobsuche"


def test_search_ohne_optionale_parameter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"stellenangebote": []})

    ergebnis = search("Data Science", transport=_transport(handler))

    assert ergebnis == []


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
