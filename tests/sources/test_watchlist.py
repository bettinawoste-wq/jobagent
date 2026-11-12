"""Tests fuer WatchlistSource, am Interface `Source` gegen gespeicherte Beispielantworten."""

import json
from pathlib import Path

import httpx
import pytest

from jobagent.job_ad import JobAd
from jobagent.sources import Source
from jobagent.sources.watchlist import WatchlistCompany, WatchlistSource

_FIXTURES = Path(__file__).parents[1] / "fixtures"
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

GREENHOUSE_COMPANY = WatchlistCompany(name="Beispiel GmbH (GH)", ats="greenhouse", slug="beispiel")
LEVER_COMPANY = WatchlistCompany(name="Beispiel GmbH", ats="lever", slug="beispiel")
BROKEN_COMPANY = WatchlistCompany(name="Kaputte Firma", ats="greenhouse", slug="kaputt")


def _successful_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "boards-api.greenhouse.io":
        if request.url.path == _GREENHOUSE_JOBS_PATH:
            return httpx.Response(200, json=GREENHOUSE_JOBS_FIXTURE)
        if request.url.path.startswith(_GREENHOUSE_JOBS_PATH + "/"):
            return httpx.Response(200, json=GREENHOUSE_DETAIL_FIXTURE)
    if request.url.host == "api.lever.co" and request.url.path == _LEVER_PATH:
        return httpx.Response(200, json=LEVER_POSTINGS_FIXTURE)
    if "kaputt" in request.url.path:
        return httpx.Response(500)
    raise AssertionError(f"Unerwartete URL: {request.url}")


def _source(companies: list[WatchlistCompany], handler=_successful_handler) -> Source:
    return WatchlistSource(companies, transport=httpx.MockTransport(handler))


def test_greenhouse_maps_matching_job_to_job_ad_with_description() -> None:
    result = _source([GREENHOUSE_COMPANY]).search(["Full-Stack"])

    assert result.job_ads == [
        JobAd(
            id="greenhouse:beispiel:1001",
            title="Full-Stack-Entwickler (m/w/d)",
            company="Beispiel GmbH",
            location="München, Deutschland",
            link="https://job-boards.greenhouse.io/beispiel/jobs/1001",
            description="Wir suchen Python & JavaScript Erfahrung.",
        )
    ]
    assert result.errors == []


def test_lever_maps_matching_posting_to_job_ad_with_plain_description() -> None:
    result = _source([LEVER_COMPANY]).search(["Full-Stack"])

    assert result.job_ads == [
        JobAd(
            id="lever:beispiel:posting-1",
            title="Full-Stack-Entwickler (m/w/d)",
            company="Beispiel GmbH",
            location="München",
            link="https://jobs.lever.co/beispiel/posting-1",
            description="Wir suchen Python Erfahrung.",
        )
    ]
    assert result.errors == []


def test_search_combines_greenhouse_and_lever() -> None:
    result = _source([GREENHOUSE_COMPANY, LEVER_COMPANY]).search(["full-stack"])

    assert [job_ad.id for job_ad in result.job_ads] == [
        "greenhouse:beispiel:1001",
        "lever:beispiel:posting-1",
    ]


def test_greenhouse_fetches_no_details_for_non_matching_jobs() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _successful_handler(request)

    result = _source([GREENHOUSE_COMPANY], handler).search(["Marketing"])

    assert result.job_ads == []
    assert paths == [_GREENHOUSE_JOBS_PATH]


def test_each_board_is_queried_once_and_each_detail_once_across_keywords() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _successful_handler(request)

    result = _source([GREENHOUSE_COMPANY, LEVER_COMPANY], handler).search(
        ["Full-Stack", "Entwickler", "Sales"]
    )

    assert sorted(job_ad.id for job_ad in result.job_ads) == [
        "greenhouse:beispiel:1001",
        "greenhouse:beispiel:1002",
        "lever:beispiel:posting-1",
        "lever:beispiel:posting-2",
    ]
    assert paths.count(_GREENHOUSE_JOBS_PATH) == 1
    assert paths.count(_LEVER_PATH) == 1
    assert paths.count(_GREENHOUSE_DETAIL_PATH) == 1
    assert paths.count("/v1/boards/beispiel/jobs/1002") == 1


def _no_connection(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("keine Verbindung", request=request)


@pytest.mark.parametrize(
    ("company", "handler", "expected"),
    [
        (BROKEN_COMPANY, _successful_handler, "Kaputte Firma: HTTP 500"),
        (BROKEN_COMPANY, _no_connection, "Kaputte Firma: keine Verbindung"),
        (
            BROKEN_COMPANY,
            lambda request: httpx.Response(200, content=b"nicht json"),
            "Kaputte Firma: ungültige Antwort",
        ),
        (
            BROKEN_COMPANY,
            lambda request: httpx.Response(200, json=[]),
            "Kaputte Firma: ungültige Antwort",
        ),
        (
            WatchlistCompany(name="Lever Kaputt", ats="lever", slug="kaputt"),
            lambda request: httpx.Response(200, json={"ok": False}),
            "Lever Kaputt: ungültige Antwort",
        ),
    ],
)
def test_search_reports_error_reason_with_company_name(company, handler, expected: str) -> None:
    result = _source([company], handler).search(["Full-Stack"])

    assert result.job_ads == []
    assert result.errors == [expected]


def test_failed_company_does_not_stop_the_others() -> None:
    result = _source([BROKEN_COMPANY, GREENHOUSE_COMPANY, LEVER_COMPANY]).search(["Full-Stack"])

    assert [job_ad.id for job_ad in result.job_ads] == [
        "greenhouse:beispiel:1001",
        "lever:beispiel:posting-1",
    ]
    assert result.errors == ["Kaputte Firma: HTTP 500"]


def test_unknown_ats_is_reported_with_company_name(caplog: pytest.LogCaptureFixture) -> None:
    mystery = WatchlistCompany(name="Mystery AG", ats="mysteryats", slug="mystery")

    with caplog.at_level("ERROR"):
        result = _source([mystery, LEVER_COMPANY]).search(["Full-Stack"])

    assert [job_ad.id for job_ad in result.job_ads] == ["lever:beispiel:posting-1"]
    assert result.errors == ["Mystery AG: unbekannter ats-Typ"]
    assert "Unbekannter ats-Typ" in caplog.text


def test_failed_greenhouse_details_leave_only_description_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _GREENHOUSE_JOBS_PATH:
            return httpx.Response(200, json=GREENHOUSE_JOBS_FIXTURE)
        return httpx.Response(500)

    result = _source([GREENHOUSE_COMPANY], handler).search(["Full-Stack"])

    assert [job_ad.id for job_ad in result.job_ads] == ["greenhouse:beispiel:1001"]
    assert result.job_ads[0].description is None
    assert result.errors == []


def test_search_without_companies_sends_no_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unerwartete Anfrage: {request.url}")

    result = _source([], handler).search(["Full-Stack"])

    assert result.job_ads == []
    assert result.errors == []


def test_malformed_greenhouse_location_is_reported_as_invalid_response() -> None:
    jobs = {"jobs": [{**job, "location": "Berlin"} for job in GREENHOUSE_JOBS_FIXTURE["jobs"]]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _GREENHOUSE_JOBS_PATH:
            return httpx.Response(200, json=jobs)
        return _successful_handler(request)

    result = _source([GREENHOUSE_COMPANY], handler).search(["Full-Stack"])

    assert result.job_ads == []
    assert result.errors == ["Beispiel GmbH (GH): ungültige Antwort"]


def test_unexpected_error_of_one_company_does_not_stop_the_others() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "kaputt" in request.url.path:
            raise RuntimeError("unerwartet")
        return _successful_handler(request)

    result = _source([BROKEN_COMPANY, LEVER_COMPANY], handler).search(["Full-Stack"])

    assert [job_ad.id for job_ad in result.job_ads] == ["lever:beispiel:posting-1"]
    assert result.errors == ["Kaputte Firma: unerwarteter Fehler"]


def test_malformed_greenhouse_details_leave_only_description_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _GREENHOUSE_DETAIL_PATH:
            return httpx.Response(200, json={"content": ["kein", "Text"]})
        return _successful_handler(request)

    result = _source([GREENHOUSE_COMPANY], handler).search(["Full-Stack"])

    assert [(job_ad.id, job_ad.description) for job_ad in result.job_ads] == [
        ("greenhouse:beispiel:1001", None)
    ]
    assert result.errors == []
