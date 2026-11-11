"""Gemeinsamer JSON-Abruf der Quellen mit Übersetzung in einen Fehlergrund.

Intern im Quellen-Paket, gehört nicht zum Interface `Source`.
"""

import html
import logging
import re
from collections.abc import Mapping

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


def html_to_text(markup: str | None) -> str | None:
    """Macht aus HTML-Beschreibungen reinen Text mit vereinheitlichtem Leerraum."""
    # Entschachtelt vor dem Tag-Strip, da Greenhouse HTML doppelt escaped
    # liefert ("&lt;div&gt;..." statt "<div>..."); für einfach escapte
    # Quellen (z.B. Arbeitnow) ist der erste unescape-Aufruf ein No-Op.
    if not markup:
        return None
    unescaped = html.unescape(markup)
    without_tags = _TAG_PATTERN.sub(" ", unescaped)
    text = html.unescape(without_tags)
    cleaned = _WHITESPACE_PATTERN.sub(" ", text).strip()
    return cleaned or None
