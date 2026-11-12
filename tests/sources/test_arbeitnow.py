"""Tests fuer ArbeitnowSource, am Interface `Source` gegen gespeicherte Beispielantworten.

Die Fixtures haben alle `created_at` 0. Das Alter einer Anzeige stellt die uebergebene
feste Uhr ein: `_days(n)` als Jetzt macht jede Fixture-Anzeige n Tage alt.
"""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from jobagent.job_ad import JobAd
from jobagent.sources import Source
from jobagent.sources.arbeitnow import ArbeitnowSource

_FIXTURES = Path(__file__).parents[1] / "fixtures"
FIXTURE = json.loads((_FIXTURES / "arbeitnow_response.json").read_text(encoding="utf-8"))
PAGE_1 = json.loads((_FIXTURES / "arbeitnow_response_seite1.json").read_text(encoding="utf-8"))
PAGE_2 = json.loads((_FIXTURES / "arbeitnow_response_seite2.json").read_text(encoding="utf-8"))


def _days(days: float) -> float:
    return days * 86400


def _source(handler, *, today: float = 1, **kwargs) -> Source:
    return ArbeitnowSource(
        transport=httpx.MockTransport(handler), now=lambda: _days(today), **kwargs
    )


def _pages(*pages: dict):
    """Handler, der die Seiten der Reihe nach liefert und die Anfragen mitschreibt."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[min(len(requests), len(pages)) - 1])

    return handler, requests


def test_search_filters_by_title_and_location_and_maps_job_ad() -> None:
    # "(m/w/d)" + "Berlin" trifft nur Eintrag 0: Eintrag 1 ist "(m/w/d)" aber
    # in Muenchen, Eintrag 2 ist in Berlin aber ohne "(m/w/d)" im Titel.
    handler, _ = _pages(FIXTURE)

    result = _source(handler, location="Berlin", published_since=14).search(["(m/w/d)"])

    assert result.job_ads == [
        JobAd(
            id="arbeitnow:full-stack-entwickler-berlin-100001",
            title="Full-Stack-Entwickler (m/w/d)",
            company="Beispiel Tech GmbH",
            location="Berlin",
            link="https://www.arbeitnow.com/jobs/companies/beispiel-tech-gmbh/full-stack-entwickler-berlin-100001",
            description="Wir suchen Python & JavaScript Erfahrung.",
        )
    ]
    assert result.errors == []


def test_search_matches_any_keyword_case_insensitively() -> None:
    handler, _ = _pages(FIXTURE)

    result = _source(handler).search(["marketing", "ALT"])

    assert [job_ad.id for job_ad in result.job_ads] == [
        "arbeitnow:online-marketing-manager-muenchen-100002",
        "arbeitnow:full-stack-entwickler-alt-berlin-100003",
    ]


def test_search_fetches_each_page_once_for_several_keywords() -> None:
    handler, requests = _pages(PAGE_1, PAGE_2)

    result = _source(handler, published_since=14).search(["Data Scientist", "Python", "Data"])

    assert len(requests) == 2
    assert [job_ad.id for job_ad in result.job_ads] == [
        "arbeitnow:data-scientist-berlin-200001",
        "arbeitnow:data-scientist-hamburg-200002",
    ]


def test_search_follows_next_link() -> None:
    handler, requests = _pages(PAGE_1, PAGE_2)

    _source(handler).search(["Data Scientist"])

    assert [str(request.url) for request in requests] == [
        "https://www.arbeitnow.com/api/job-board-api",
        "https://www.arbeitnow.com/api/job-board-api?page=2",
    ]


def test_search_fetches_at_most_ten_pages_per_run() -> None:
    handler, requests = _pages(PAGE_1)  # verweist immer wieder auf eine naechste Seite

    result = _source(handler).search(["Data Scientist", "Python"])

    assert len(requests) == 10
    assert [job_ad.id for job_ad in result.job_ads] == ["arbeitnow:data-scientist-berlin-200001"]
    assert result.errors == []


def test_search_stops_paging_at_job_ads_older_than_published_since() -> None:
    handler, requests = _pages(PAGE_1, PAGE_2)

    result = _source(handler, today=60, published_since=7).search(["Data Scientist"])

    assert result.job_ads == []
    assert len(requests) == 1


def test_search_without_published_since_ignores_age() -> None:
    handler, requests = _pages(PAGE_1, PAGE_2)

    result = _source(handler, today=365).search(["Data Scientist"])

    assert len(result.job_ads) == 2
    assert len(requests) == 2


def test_search_keeps_young_job_ads_of_the_page_that_stops_paging() -> None:
    page = deepcopy(PAGE_1)
    page["data"].append({**page["data"][0], "slug": "neu-200009", "created_at": _days(59)})
    handler, requests = _pages(page, PAGE_2)

    result = _source(handler, today=60, published_since=7).search(["Data Scientist"])

    assert [job_ad.id for job_ad in result.job_ads] == ["arbeitnow:neu-200009"]
    assert len(requests) == 1


def test_search_without_keywords_fetches_nothing() -> None:
    handler, requests = _pages(PAGE_1)

    result = _source(handler).search([])

    assert result.job_ads == []
    assert result.errors == []
    assert requests == []


def _no_connection(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("keine Verbindung", request=request)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(503), "Data Scientist, Python: HTTP 503"),
        (_no_connection, "Data Scientist, Python: keine Verbindung"),
        (httpx.Response(200, content=b"nicht json"), "Data Scientist, Python: ungültige Antwort"),
        (httpx.Response(200, json=[]), "Data Scientist, Python: ungültige Antwort"),
        (
            httpx.Response(200, json={"data": [{"title": "ohne slug"}]}),
            "Data Scientist, Python: ungültige Antwort",
        ),
    ],
)
def test_search_keeps_job_ads_found_before_paging_aborts(response, expected: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=PAGE_1)
        return response(request) if callable(response) else response

    result = _source(handler).search(["Data Scientist", "Python"])

    assert [job_ad.id for job_ad in result.job_ads] == ["arbeitnow:data-scientist-berlin-200001"]
    assert result.errors == [expected]


def test_search_reports_malformed_links_as_invalid_response() -> None:
    page = {**deepcopy(PAGE_1), "links": "kaputt"}
    handler, _ = _pages(page)

    result = _source(handler).search(["Data Scientist", "Python"])

    assert [job_ad.id for job_ad in result.job_ads] == ["arbeitnow:data-scientist-berlin-200001"]
    assert result.errors == ["Data Scientist, Python: ungültige Antwort"]


def _with_first_entry(**changes: object) -> dict:
    page = deepcopy(FIXTURE)
    page["data"][0].update(changes)
    return page


def test_entry_with_link_of_wrong_type_is_dropped_and_reported_once() -> None:
    page = _with_first_entry(url=42)
    page["data"][2]["url"] = ["Liste"]
    handler, _ = _pages(page)

    result = _source(handler).search(["(m/w/d)", "alt"])

    assert [job_ad.id for job_ad in result.job_ads] == [
        "arbeitnow:online-marketing-manager-muenchen-100002"
    ]
    assert result.errors == ["(m/w/d), alt: ungültige Antwort"]


def test_optional_fields_of_wrong_type_become_none() -> None:
    handler, _ = _pages(_with_first_entry(company_name=["Liste"], location=42, description=7))

    result = _source(handler).search(["Full-Stack-Entwickler (m/w/d)"])

    first = result.job_ads[0]
    assert (first.company, first.location, first.description) == (None, None, None)
    assert result.errors == []


def test_location_of_wrong_type_does_not_match_location_filter() -> None:
    handler, _ = _pages(_with_first_entry(location=42))

    result = _source(handler, location="Berlin").search(["Full-Stack"])

    assert [job_ad.id for job_ad in result.job_ads] == [
        "arbeitnow:full-stack-entwickler-alt-berlin-100003"
    ]
    assert result.errors == []


def test_dropped_entry_stays_reported_when_a_later_page_fails() -> None:
    page = deepcopy(PAGE_1)
    page["data"][0]["url"] = 42

    def handler(request: httpx.Request) -> httpx.Response:
        if "page=2" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(200, json=page)

    result = _source(handler).search(["Data Scientist"])

    assert result.job_ads == []
    assert result.errors == ["Data Scientist: ungültige Antwort", "Data Scientist: HTTP 503"]
