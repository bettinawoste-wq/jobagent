"""Gemeinsamer JSON-Abruf der Quellen mit Übersetzung in einen Fehlergrund,
dazu die Prüfung der Eintragslisten und der lokale Titel-Filter.

Intern im Quellen-Paket, gehört nicht zum Interface `Source`.
"""

import html
import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 30.0
INVALID_RESPONSE = "ungültige Antwort"
_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class FetchError(Exception):
    """Abruf gescheitert; `reason` ist der Grund für den Quellenstatus."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@contextmanager
def malformed_as_invalid(what: str, where: str) -> Iterator[None]:
    """Macht aus verformten inneren Feldern (falscher Typ, fehlender Index) einen FetchError.

    Eine Quelle wirft nie: Liest sie eine Antwort aus und stößt dabei auf eine Form, die
    sie nicht erwartet, gilt die ganze Antwort als "ungültige Antwort".
    """
    try:
        yield
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        logger.exception("%s hat unerwartetes Format (%s)", what, where)
        raise FetchError(INVALID_RESPONSE) from error


def get_json(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, str | int] | None = None,
    headers: Mapping[str, str] | None = None,
) -> object:
    """Holt JSON; jeder Fehler wird geloggt und als FetchError mit Grund geworfen.

    Gründe: "HTTP nnn", "keine Verbindung" oder "ungültige Antwort". Ob das JSON die
    erwartete Form hat, prüft der Aufrufer.
    """
    try:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as error:
        logger.exception("Anfrage fehlgeschlagen (url=%r)", url)
        raise FetchError(f"HTTP {error.response.status_code}") from error
    except httpx.HTTPError as error:
        logger.exception("Anfrage fehlgeschlagen (url=%r)", url)
        raise FetchError("keine Verbindung") from error
    except ValueError as error:
        logger.exception("Antwort ist kein gültiges JSON (url=%r)", url)
        raise FetchError(INVALID_RESPONSE) from error


def entries_with_ids(
    entries: object,
    id_field: str,
    *,
    id_type: type | tuple[type, ...] = (str, int),
    what: str,
    where: str,
) -> list[dict]:
    """Gibt `entries` zurück, wenn es eine Liste von dicts mit gesetztem ID-Feld ist.

    Gesetzt heißt: nicht leer und vom Typ `id_type` (ohne bool).

    Sonst wird "<what> hat unerwartetes Format (<where>)" geloggt und FetchError mit
    "ungültige Antwort" geworfen: Schon ein Eintrag ohne ID macht die Antwort ungültig.
    """
    if not isinstance(entries, list) or not all(
        isinstance(entry, dict) and _is_id(entry.get(id_field), id_type) for entry in entries
    ):
        logger.error("%s hat unerwartetes Format (%s)", what, where)
        raise FetchError(INVALID_RESPONSE)
    return entries


def _is_id(value: object, id_type: type | tuple[type, ...]) -> bool:
    return isinstance(value, id_type) and not isinstance(value, bool) and value != ""


def title_matches(title: object, keywords: list[str]) -> bool:
    """Lokaler Filter für Quellen ohne Stichwortsuche: ein Suchbegriff im Titel genügt."""
    text = title.lower() if isinstance(title, str) else ""
    return any(keyword.lower() in text for keyword in keywords)


def html_to_text(markup: object) -> str | None:
    """Macht aus HTML-Beschreibungen reinen Text mit vereinheitlichtem Leerraum.

    Ist die Beschreibung kein Text, gibt es keine: None.
    """
    # Entschachtelt vor dem Tag-Strip, da Greenhouse HTML doppelt escaped
    # liefert ("&lt;div&gt;..." statt "<div>..."); für einfach escapte
    # Quellen (z.B. Arbeitnow) ist der erste unescape-Aufruf ein No-Op.
    if not markup or not isinstance(markup, str):
        return None
    unescaped = html.unescape(markup)
    without_tags = _TAG_PATTERN.sub(" ", unescaped)
    text = html.unescape(without_tags)
    cleaned = _WHITESPACE_PATTERN.sub(" ", text).strip()
    return cleaned or None
