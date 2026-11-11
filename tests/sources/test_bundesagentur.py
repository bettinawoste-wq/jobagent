"""Tests fuer BundesagenturSource, am Interface `Source` gegen gespeicherte Beispielantworten."""

import base64
import json
from pathlib import Path

import httpx
import pytest

from jobagent.job_ad import JobAd
from jobagent.sources import Source
from jobagent.sources.bundesagentur import BundesagenturSource

_FIXTURES = Path(__file__).parents[1] / "fixtures"
SEARCH_FIXTURE = json.loads((_FIXTURES / "jobsuche_response.json").read_text(encoding="utf-8"))
DETAILS_FIXTURE = json.loads((_FIXTURES / "jobdetails_response.json").read_text(encoding="utf-8"))

_SEARCH_PATH = "/jobboerse/jobsuche-service/pc/v6/jobs"
_DETAILS_PREFIX = "/jobboerse/jobsuche-service/pc/v4/jobdetails/"


def _successful_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == _SEARCH_PATH:
        return httpx.Response(200, json=SEARCH_FIXTURE)
    if request.url.path.startswith(_DETAILS_PREFIX):
        code = request.url.path.removeprefix(_DETAILS_PREFIX)
        reference = base64.b64decode(code).decode()
        return httpx.Response(200, json=DETAILS_FIXTURE[reference])
    raise AssertionError(f"Unerwartete URL: {request.url}")


def _source(handler, **kwargs) -> Source:
    return BundesagenturSource(transport=httpx.MockTransport(handler), **kwargs)


def test_search_maps_response_to_job_ads_including_details() -> None:
    result = _source(_successful_handler).search(["Softwareentwicklerin"])

    assert result.job_ads == [
        JobAd(
            id="10001-1003353506-S",
            title="Softwareentwickler/in Linux (m/w/d)",
            company="Beispiel GmbH",
            location="München",
            link="https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003353506-S",
            description=(
                "Wir suchen eine Softwareentwicklerin fuer unser Backend-Team in "
                "Python und C++. Aufgaben: API-Design, CI/CD, Code-Reviews. "
                "Erfahrung mit Cloud-Migration von Vorteil."
            ),
        ),
        JobAd(
            id="10001-1003353507-S",
            title="IT Consultant (m/w/d)",
            company="Consulting AG",
            location="Garching",
            link="https://www.consulting-ag.example/karriere/it-consultant",
            description=None,
        ),
    ]
    assert result.errors == []


def test_search_sends_search_parameters_and_header() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _successful_handler(request)

    _source(handler, location="München", radius=30, published_since=7).search(
        ["Softwareentwicklerin"]
    )

    search_request = next(r for r in requests if r.url.path == _SEARCH_PATH)
    params = search_request.url.params
    assert params["was"] == "Softwareentwicklerin"
    assert params["wo"] == "München"
    assert params["umkreis"] == "30"
    assert params["veroeffentlichtseit"] == "7"
    assert all(r.headers["X-API-Key"] == "jobboerse-jobsuche" for r in requests)


def test_search_without_optional_parameters_sends_only_keyword() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ergebnisliste": []})

    _source(handler).search(["Data Science"])

    assert dict(requests[0].url.params) == {"was": "Data Science"}


def test_search_finds_job_ad_once_and_fetches_its_details_once_across_keywords() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _successful_handler(request)

    result = _source(handler).search(["Softwareentwicklerin", "IT Consultant"])

    assert [job_ad.id for job_ad in result.job_ads] == ["10001-1003353506-S", "10001-1003353507-S"]
    search_keywords = [r.url.params["was"] for r in requests if r.url.path == _SEARCH_PATH]
    assert search_keywords == ["Softwareentwicklerin", "IT Consultant"]
    assert len([r for r in requests if r.url.path.startswith(_DETAILS_PREFIX)]) == 2


def test_search_without_matches_fetches_no_details() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ergebnisliste": []})

    result = _source(handler).search(["Data Science"])

    assert result.job_ads == []
    assert result.errors == []
    assert len(requests) == 1


def _no_connection(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("keine Verbindung", request=request)


def _not_json(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"nicht json")


def _entry_without_reference(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ergebnisliste": [{"titel": "ohne Referenznummer"}]})


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (lambda request: httpx.Response(500), "Data Science: HTTP 500"),
        (_no_connection, "Data Science: keine Verbindung"),
        (_not_json, "Data Science: ungültige Antwort"),
        (_entry_without_reference, "Data Science: ungültige Antwort"),
    ],
)
def test_search_reports_error_reason_with_keyword(handler, expected: str) -> None:
    result = _source(handler).search(["Data Science"])

    assert result.job_ads == []
    assert result.errors == [expected]


def test_failed_keyword_does_not_stop_the_others() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("was") == "kaputt":
            return httpx.Response(503)
        return _successful_handler(request)

    result = _source(handler).search(["kaputt", "Softwareentwicklerin"])

    assert len(result.job_ads) == 2
    assert result.errors == ["kaputt: HTTP 503"]


def test_failed_details_leave_only_description_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _SEARCH_PATH:
            return httpx.Response(200, json=SEARCH_FIXTURE)
        return httpx.Response(500)

    result = _source(handler).search(["Softwareentwicklerin"])

    assert len(result.job_ads) == 2
    assert all(job_ad.description is None for job_ad in result.job_ads)
    assert result.errors == []
