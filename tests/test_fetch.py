"""Tests fuer fetch.py, ausschliesslich gegen gespeicherte Beispielantworten."""

import json
import time
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from jobagent import fetch
from jobagent.job_ad import JobAd


def search_arbeitnow(*args, **kwargs) -> list[JobAd]:
    return fetch.search_arbeitnow(*args, **kwargs).job_ads


_FIXTURES = Path(__file__).parent / "fixtures"
ARBEITNOW_FIXTURE = json.loads((_FIXTURES / "arbeitnow_response.json").read_text(encoding="utf-8"))
ARBEITNOW_SEITE1 = json.loads(
    (_FIXTURES / "arbeitnow_response_seite1.json").read_text(encoding="utf-8")
)
ARBEITNOW_SEITE2 = json.loads(
    (_FIXTURES / "arbeitnow_response_seite2.json").read_text(encoding="utf-8")
)


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


def test_search_arbeitnow_filtert_nach_titel_und_ort() -> None:
    # "(m/w/d)" + "Berlin" trifft nur Eintrag 0: Eintrag 1 ist "(m/w/d)" aber
    # in Muenchen, Eintrag 2 ist in Berlin aber ohne "(m/w/d)" im Titel.
    daten = _mit_alter(ARBEITNOW_FIXTURE, {0: 1, 1: 1})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=daten)

    ergebnis = search_arbeitnow(
        "(m/w/d)", wo="Berlin", veroeffentlichtseit=14, transport=_transport(handler)
    )

    assert [a.title for a in ergebnis] == ["Full-Stack-Entwickler (m/w/d)"]
    assert ergebnis[0].id == "arbeitnow:full-stack-entwickler-berlin-100001"
    assert ergebnis[0].company == "Beispiel Tech GmbH"
    assert ergebnis[0].location == "Berlin"


def test_search_arbeitnow_bereinigt_html_in_beschreibung() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ARBEITNOW_FIXTURE)

    ergebnis = search_arbeitnow("(m/w/d)", wo="Berlin", transport=_transport(handler))

    assert [a.title for a in ergebnis] == ["Full-Stack-Entwickler (m/w/d)"]
    assert ergebnis[0].description == "Wir suchen Python & JavaScript Erfahrung."


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


def test_search_arbeitnow_meldet_fehler_und_behaelt_bisherige_treffer() -> None:
    seite1 = _mit_alter(ARBEITNOW_SEITE1, {0: 1})
    aufrufe = []

    def handler(request: httpx.Request) -> httpx.Response:
        aufrufe.append(request)
        return httpx.Response(200, json=seite1) if len(aufrufe) == 1 else httpx.Response(503)

    ergebnis = fetch.search_arbeitnow(
        "Data Scientist", veroeffentlichtseit=14, transport=_transport(handler)
    )

    assert len(ergebnis.job_ads) == 1
    assert ergebnis.fehler == ["Data Scientist: HTTP 503"]
