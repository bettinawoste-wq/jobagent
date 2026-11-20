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

    _source(handler, location="München", radius=30, search_window=7).search(
        ["Softwareentwicklerin"]
    )

    search_request = next(r for r in requests if r.url.path == _SEARCH_PATH)
    params = search_request.url.params
    assert params["was"] == "Softwareentwicklerin"
    assert params["wo"] == "München"
    assert params["umkreis"] == "30"
    assert params["veroeffentlichtseit"] == "7"
    assert all(r.headers["X-API-Key"] == "jobboerse-jobsuche" for r in requests)


def test_search_without_optional_parameters_sends_only_keyword_and_page() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ergebnisliste": []})

    _source(handler).search(["Data Science"])

    assert set(requests[0].url.params) == {"was", "page", "size"}
    assert requests[0].url.params["was"] == "Data Science"
    assert requests[0].url.params["page"] == "1"


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


def _search_with_first_entry(**changes: object):
    """Handler, der die Beispielantwort mit geändertem ersten Eintrag liefert."""
    first, *rest = SEARCH_FIXTURE["ergebnisliste"]
    search = {**SEARCH_FIXTURE, "ergebnisliste": [{**first, **changes}, *rest]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _SEARCH_PATH:
            return httpx.Response(200, json=search)
        return _successful_handler(request)

    return handler


def test_malformed_reference_is_reported_as_invalid_response_with_keyword() -> None:
    result = _source(_search_with_first_entry(referenznummer=10001)).search(["Data Science"])

    assert result.job_ads == []
    assert result.errors == ["Data Science: ungültige Antwort"]


@pytest.mark.parametrize(
    "locations",
    [["München"], {"adresse": {"ort": "München"}}, [{"adresse": "München"}]],
    ids=["location-not-dict", "locations-not-list", "address-not-dict"],
)
def test_location_container_of_wrong_type_leaves_only_location_empty(locations: object) -> None:
    result = _source(_search_with_first_entry(stellenlokationen=locations)).search(["Data Science"])

    assert [(job_ad.id, job_ad.location) for job_ad in result.job_ads] == [
        ("10001-1003353506-S", None),
        ("10001-1003353507-S", "Garching"),
    ]
    assert result.errors == []


def test_entry_with_title_of_wrong_type_is_dropped_and_reported_once() -> None:
    handler = _search_with_first_entry(stellenangebotsTitel=42, hauptberuf=["Liste"])

    result = _source(handler).search(["Data Science"])

    assert [job_ad.id for job_ad in result.job_ads] == ["10001-1003353507-S"]
    assert result.errors == ["Data Science: ungültige Antwort"]


def test_optional_fields_of_wrong_type_become_none_and_link_falls_back() -> None:
    handler = _search_with_first_entry(
        stellenangebotsTitel=True,
        firma=["Beispiel GmbH"],
        stellenlokationen=[{"adresse": {"ort": 80331}}],
        externeURL={"url": "https://example.com"},
    )

    result = _source(handler).search(["Data Science"])

    first = result.job_ads[0]
    assert (first.title, first.company, first.location, first.link) == (
        "Softwareentwickler/in",
        None,
        None,
        "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003353506-S",
    )
    assert result.errors == []


def test_description_of_wrong_type_becomes_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith(_DETAILS_PREFIX):
            return httpx.Response(200, json={"stellenangebotsBeschreibung": 42})
        return _successful_handler(request)

    result = _source(handler).search(["Data Science"])

    assert [job_ad.description for job_ad in result.job_ads] == [None, None]
    assert result.errors == []


def test_title_of_wrong_type_without_fallback_drops_the_entry() -> None:
    first = {**SEARCH_FIXTURE["ergebnisliste"][0], "stellenangebotsTitel": 42}
    del first["hauptberuf"]
    search = {**SEARCH_FIXTURE, "ergebnisliste": [first, *SEARCH_FIXTURE["ergebnisliste"][1:]]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _SEARCH_PATH:
            return httpx.Response(200, json=search)
        return _successful_handler(request)

    result = _source(handler).search(["Data Science"])

    assert [job_ad.id for job_ad in result.job_ads] == ["10001-1003353507-S"]
    assert result.errors == ["Data Science: ungültige Antwort"]


def _numbered_entry(number: int) -> dict:
    return {**SEARCH_FIXTURE["ergebnisliste"][0], "referenznummer": f"10001-{number}-S"}


def _paging_handler(total: int, requests: list[httpx.Request], *, with_count: bool = True):
    """Handler, der `total` Anzeigen seitenweise nach `page` und `size` der Anfrage liefert."""
    entries = [_numbered_entry(number) for number in range(1, total + 1)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != _SEARCH_PATH:
            return httpx.Response(200, json={})
        requests.append(request)
        page = int(request.url.params["page"])
        size = int(request.url.params["size"])
        body: dict = {"ergebnisliste": entries[(page - 1) * size : page * size]}
        if with_count:
            body["maxErgebnisse"] = total
        return httpx.Response(200, json=body)

    return handler


def _page_size() -> int:
    """Die Seitengröße, die die Quelle anfragt."""
    requests: list[httpx.Request] = []
    _source(_paging_handler(1, requests)).search(["Data Science"])
    return int(requests[0].url.params["size"])


def test_search_pages_through_all_results_of_a_keyword() -> None:
    requests: list[httpx.Request] = []
    size = _page_size()

    result = _source(_paging_handler(size + 1, requests)).search(["Data Science"])

    assert len(result.job_ads) == size + 1
    assert result.errors == []
    assert [r.url.params["page"] for r in requests] == ["1", "2"]


def test_search_follows_the_total_count_when_the_api_sends_smaller_pages() -> None:
    # Hält sich die API nicht an `size`, ist eine kürzere Seite noch nicht die letzte.
    entries = [_numbered_entry(number) for number in range(1, 61)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != _SEARCH_PATH:
            return httpx.Response(200, json={})
        requests.append(request)
        page = int(request.url.params["page"])
        body = {"ergebnisliste": entries[(page - 1) * 25 : page * 25], "maxErgebnisse": 60}
        return httpx.Response(200, json=body)

    result = _source(handler).search(["Data Science"])

    assert len(result.job_ads) == 60
    assert result.errors == []
    assert len(requests) == 3


def _pages_handler(pages: list[list[dict]], total: int, requests: list[httpx.Request]):
    """Handler, der feste Seiten mit der Gesamtzahl `total` liefert, danach leere."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != _SEARCH_PATH:
            return httpx.Response(200, json={})
        requests.append(request)
        page = int(request.url.params["page"])
        entries = pages[page - 1] if page <= len(pages) else []
        return httpx.Response(200, json={"ergebnisliste": entries, "maxErgebnisse": total})

    return handler


def test_search_ends_at_an_empty_page_if_the_total_count_is_too_high() -> None:
    numbered = [_numbered_entry(number) for number in range(1, 116)]
    pages = [numbered[:50], numbered[50:100], numbered[100:]]
    requests: list[httpx.Request] = []

    result = _source(_pages_handler(pages, 120, requests)).search(["Data Science"])

    assert len(result.job_ads) == 115
    assert result.errors == []
    assert len(requests) == 4


def test_search_goes_on_after_a_short_later_page_while_the_total_is_not_reached() -> None:
    # Verschwinden zwischen zwei Abrufen Anzeigen, ist eine Seite kürzer, aber nicht die letzte.
    numbered = [_numbered_entry(number) for number in range(1, 141)]
    pages = [numbered[:50], numbered[50:98], numbered[98:140]]
    requests: list[httpx.Request] = []

    result = _source(_pages_handler(pages, 140, requests)).search(["Data Science"])

    assert len(result.job_ads) == 140
    assert result.errors == []


def test_search_ends_at_a_page_that_only_repeats_job_ads() -> None:
    # Wiederholt die API für Seiten hinter dem Ende die letzte, ist nichts abgeschnitten.
    numbered = [_numbered_entry(number) for number in range(1, 31)]
    requests: list[httpx.Request] = []

    result = _source(_pages_handler([numbered] * 5, 120, requests)).search(["Data Science"])

    assert len(result.job_ads) == 30
    assert result.errors == []
    assert len(requests) == 2


def test_search_counts_job_ads_repeated_across_pages_only_once() -> None:
    # Verschieben sich die Ergebnisse zwischen zwei Abrufen, wiederholt die API Einträge.
    numbered = [_numbered_entry(number) for number in range(1, 101)]
    pages = [numbered[:50], numbered[40:90], numbered[90:]]
    requests: list[httpx.Request] = []

    result = _source(_pages_handler(pages, 100, requests)).search(["Data Science"])

    assert len(result.job_ads) == 100
    assert result.errors == []


def test_search_stops_at_a_short_page_without_total_count() -> None:
    requests: list[httpx.Request] = []

    result = _source(_paging_handler(3, requests, with_count=False)).search(["Data Science"])

    assert len(result.job_ads) == 3
    assert result.errors == []
    assert len(requests) == 1


def test_search_reports_truncated_results_when_page_limit_is_reached() -> None:
    requests: list[httpx.Request] = []

    result = _source(_paging_handler(100_000, requests)).search(["Data Science", "Python"])

    pages_per_keyword = len(requests) // 2
    assert 1 < pages_per_keyword < 20  # eine Sicherheitsgrenze, maßvoll (ADR 0002)
    assert len(result.job_ads) == pages_per_keyword * _page_size()
    assert result.errors == [
        f"Data Science: Ergebnisse abgeschnitten nach {pages_per_keyword} Seiten",
        f"Python: Ergebnisse abgeschnitten nach {pages_per_keyword} Seiten",
    ]


def test_failed_later_page_keeps_job_ads_of_earlier_pages() -> None:
    requests: list[httpx.Request] = []
    paging = _paging_handler(100_000, requests)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(503)
        return paging(request)

    result = _source(handler).search(["Data Science"])

    assert len(result.job_ads) == _page_size()
    assert result.errors == ["Data Science: HTTP 503"]
