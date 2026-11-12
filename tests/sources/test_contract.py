"""Vertragstest am Interface `Source`: Keine Quelle wirft, auch nicht bei kaputten Antworten.

Jeder Adapter in `ADAPTERS` bekommt dieselben verformten Antworten. Für jeden Fall gilt:
`search` wirft nicht, und jeder Fehler hat die Form "<Suchbegriffe oder Firma>: <Grund>"
mit einem der Gründe aus `_http.py`. Ein neuer Adapter ist abgedeckt, sobald er in
`ADAPTERS` steht.
"""

import copy
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from jobagent.sources import Source
from jobagent.sources.arbeitnow import ArbeitnowSource
from jobagent.sources.bundesagentur import BundesagenturSource
from jobagent.sources.watchlist import WatchlistCompany, WatchlistSource

_KEYWORD = "Entwickler"
_TWO_KEYWORDS = [_KEYWORD, "Data Scientist"]
_NOW = 1_700_000_000
# Nur die Gründe, die `_http.py` vergibt; ein Auffanggrund wie "unerwarteter Fehler"
# hieße, dass ein Adapter eine verformte Antwort nicht selbst erkennt.
_KNOWN_REASONS = r"HTTP \d{3}|keine Verbindung|ungültige Antwort"

# Weg zu einem Feld in einer JSON-Antwort: Schlüssel und Listenindizes.
JsonPath = tuple[str | int, ...]


@dataclass(frozen=True)
class Adapter:
    """Ein Adapter mit einer gültigen Antwort, die der Test gezielt verformt.

    `search_body` beantwortet die Suche, `detail_body` (falls es einen Detail-Call gibt)
    die Detail-Anfragen; `is_detail` erkennt eine Detail-Anfrage an ihrer URL.
    `subjects` nennt zu den Suchbegriffen, was vor dem Doppelpunkt eines Fehlers stehen darf.
    """

    name: str
    build: Callable[[httpx.BaseTransport], Source]
    subjects: Callable[[list[str]], list[str]]
    search_body: object
    detail_body: object | None = None
    is_detail: Callable[[httpx.Request], bool] = lambda request: False


_GREENHOUSE = WatchlistCompany(name="Beispiel GmbH (GH)", ats="greenhouse", slug="beispiel")
_LEVER = WatchlistCompany(name="Beispiel GmbH (Lever)", ats="lever", slug="beispiel")

ADAPTERS = [
    Adapter(
        name="Bundesagentur",
        build=lambda transport: BundesagenturSource("München", 25, 7, transport=transport),
        # Je Suchbegriff eine Anfrage, also je Suchbegriff ein Fehler.
        subjects=lambda keywords: keywords,
        search_body={
            "ergebnisliste": [
                {
                    "referenznummer": "10001-1-S",
                    "stellenangebotsTitel": "Entwickler (m/w/d)",
                    "hauptberuf": "Softwareentwickler/in",
                    "firma": "Beispiel GmbH",
                    "stellenlokationen": [{"adresse": {"ort": "München"}}],
                    "externeURL": "https://example.com/1",
                }
            ]
        },
        detail_body={
            "stellenangebotsBeschreibung": "Wir suchen eine Entwicklerin.",
            "stellenbeschreibung": "Wir suchen eine Entwicklerin.",
        },
        is_detail=lambda request: "/jobdetails/" in request.url.path,
    ),
    Adapter(
        name="Arbeitnow",
        build=lambda transport: ArbeitnowSource("Berlin", 7, transport=transport, now=lambda: _NOW),
        # Eine Anfrage für alle Suchbegriffe, also ein Fehler mit allen Begriffen.
        subjects=lambda keywords: [", ".join(keywords)],
        search_body={
            "data": [
                {
                    "slug": "entwickler-beispiel",
                    "title": "Entwickler (m/w/d)",
                    "company_name": "Beispiel GmbH",
                    "location": "Berlin",
                    "url": "https://example.com/1",
                    "description": "<p>Wir suchen eine Entwicklerin.</p>",
                    "created_at": _NOW,
                }
            ],
            "links": {"next": None},
        },
    ),
    Adapter(
        name="Watchlist-Greenhouse",
        build=lambda transport: WatchlistSource([_GREENHOUSE], transport=transport),
        subjects=lambda keywords: [_GREENHOUSE.name],
        search_body={
            "jobs": [
                {
                    "id": 1001,
                    "title": "Entwickler (m/w/d)",
                    "company_name": "Beispiel GmbH",
                    "location": {"name": "München"},
                    "absolute_url": "https://example.com/1",
                }
            ]
        },
        detail_body={"content": "&lt;p&gt;Wir suchen eine Entwicklerin.&lt;/p&gt;"},
        # Suche: .../boards/{slug}/jobs, Detail: .../boards/{slug}/jobs/{id}
        is_detail=lambda request: not request.url.path.endswith("/jobs"),
    ),
    Adapter(
        name="Watchlist-Lever",
        build=lambda transport: WatchlistSource([_LEVER], transport=transport),
        subjects=lambda keywords: [_LEVER.name],
        search_body=[
            {
                "id": "abc-123",
                "text": "Entwickler (m/w/d)",
                "categories": {"location": "Berlin"},
                "hostedUrl": "https://example.com/1",
                "descriptionPlain": "Wir suchen eine Entwicklerin.",
            }
        ],
    ),
]


def _raise_connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Verbindung abgebrochen", request=request)


def _raise_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("Zeitüberschreitung", request=request)


# Verformte Antworten, die für jeden Abruf eines Adapters gelten.
_WHOLE_RESPONSES: dict[str, Callable[[httpx.Request], httpx.Response]] = {
    "text-statt-json": lambda request: httpx.Response(200, text="<html>Wartung</html>"),
    "leere-antwort": lambda request: httpx.Response(200, text=""),
    "zahl-oben": lambda request: httpx.Response(200, json=42),
    "text-oben": lambda request: httpx.Response(200, json="Text"),
    "null-oben": lambda request: httpx.Response(200, json=None),
    "objekt-oben": lambda request: httpx.Response(200, json={"Feld": "Objekt"}),
    "leere-liste-oben": lambda request: httpx.Response(200, json=[]),
    "http-404": lambda request: httpx.Response(404),
    "http-500": lambda request: httpx.Response(500),
    "verbindungsabbruch": _raise_connect_error,
    "timeout": _raise_timeout,
}

# Ersatzwerte mit falschem Typ: Zahl statt Text, Text statt Objekt, Liste statt Objekt …
_WRONG_VALUES: dict[str, object] = {
    "zahl": 42,
    "text": "Text",
    "liste": ["Liste"],
    "objekt": {"Feld": "Objekt"},
    "null": None,
    "bool": True,
}


def _paths(value: Any, path: JsonPath = ()) -> Iterator[JsonPath]:
    """Alle Pfade unterhalb von `value` (Schlüssel bzw. Listenindex), ohne die Wurzel."""
    children = (
        value.items()
        if isinstance(value, dict)
        else enumerate(value)
        if isinstance(value, list)
        else ()
    )
    for key, child in children:
        yield (*path, key)
        yield from _paths(child, (*path, key))


def _get(value: Any, path: JsonPath) -> Any:
    for key in path:
        value = value[key]
    return value


def _replaced(body: object, path: JsonPath, new: object) -> object:
    result = copy.deepcopy(body)
    _get(result, path[:-1])[path[-1]] = new
    return result


def _removed(body: object, path: JsonPath) -> object:
    result = copy.deepcopy(body)
    del _get(result, path[:-1])[path[-1]]
    return result


def _mutations(body: object) -> Iterator[tuple[str, object]]:
    """Jede Verformung der gültigen Antwort: fehlendes Feld oder Feld mit falschem Typ."""
    for path in _paths(body):
        label = "/".join(str(key) for key in path)
        yield f"{label}-fehlt", _removed(body, path)
        original = _get(body, path)
        if isinstance(original, list) and original:
            yield f"{label}-leere-liste", _replaced(body, path, [])
        for name, wrong in _WRONG_VALUES.items():
            if type(wrong) is not type(original):
                yield f"{label}-{name}", _replaced(body, path, wrong)


@dataclass(frozen=True)
class Case:
    adapter: Adapter
    handler: Callable[[httpx.Request], httpx.Response]


def _respond(
    adapter: Adapter,
    search: Callable[[httpx.Request], httpx.Response],
    detail: Callable[[httpx.Request], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    """Beantwortet Such- und Detail-Anfragen getrennt."""

    def handler(request: httpx.Request) -> httpx.Response:
        return detail(request) if adapter.is_detail(request) else search(request)

    return handler


def _json(body: object) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, json=body)


def _cases() -> Iterator[object]:
    for adapter in ADAPTERS:
        valid_search, valid_detail = _json(adapter.search_body), _json(adapter.detail_body)
        for name, handler in _WHOLE_RESPONSES.items():
            yield pytest.param(Case(adapter, handler), id=f"{adapter.name}-{name}")
        for name, body in _mutations(adapter.search_body):
            handler = _respond(adapter, _json(body), valid_detail)
            yield pytest.param(Case(adapter, handler), id=f"{adapter.name}-suche-{name}")
        if adapter.detail_body is not None:
            for name, body in _mutations(adapter.detail_body):
                handler = _respond(adapter, valid_search, _json(body))
                yield pytest.param(Case(adapter, handler), id=f"{adapter.name}-detail-{name}")
            for name, broken in _WHOLE_RESPONSES.items():
                handler = _respond(adapter, valid_search, broken)
                yield pytest.param(Case(adapter, handler), id=f"{adapter.name}-detail-{name}")


def _error_pattern(adapter: Adapter, keywords: list[str]) -> re.Pattern[str]:
    subjects = "|".join(re.escape(subject) for subject in adapter.subjects(keywords))
    return re.compile(rf"(?:{subjects}): (?:{_KNOWN_REASONS})")


@pytest.mark.parametrize("case", list(_cases()))
def test_search_never_raises_and_reports_errors_uniformly(case: Case) -> None:
    source = case.adapter.build(httpx.MockTransport(case.handler))

    result = source.search([_KEYWORD])

    pattern = _error_pattern(case.adapter, [_KEYWORD])
    for error in result.errors:
        assert pattern.fullmatch(error), error


# Antworten, die für jeden Adapter ein Fehler sind; ein Objekt oder eine leere Liste oben
# kann je nach Adapter eine gültige Antwort ohne Treffer sein.
_ALWAYS_ERRORS = [
    name for name in _WHOLE_RESPONSES if name not in {"objekt-oben", "leere-liste-oben"}
]


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda adapter: adapter.name)
@pytest.mark.parametrize("broken", _ALWAYS_ERRORS)
def test_broken_response_is_reported_as_one_error(adapter: Adapter, broken: str) -> None:
    source = adapter.build(httpx.MockTransport(_WHOLE_RESPONSES[broken]))

    result = source.search([_KEYWORD])

    assert result.job_ads == []
    assert len(result.errors) == 1


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda adapter: adapter.name)
@pytest.mark.parametrize("broken", _ALWAYS_ERRORS)
def test_errors_with_two_keywords_name_keywords_or_company(adapter: Adapter, broken: str) -> None:
    source = adapter.build(httpx.MockTransport(_WHOLE_RESPONSES[broken]))

    result = source.search(_TWO_KEYWORDS)

    pattern = _error_pattern(adapter, _TWO_KEYWORDS)
    assert result.errors
    for error in result.errors:
        assert pattern.fullmatch(error), error
