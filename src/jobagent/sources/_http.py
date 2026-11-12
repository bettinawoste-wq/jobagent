"""Gemeinsamer JSON-Abruf der Quellen mit Übersetzung in einen Fehlergrund,
dazu die Prüfung der Eintragslisten, die Typprüfung der Felder einer Anzeige
(`required_text`, `text_or_none`, `convert_entries`) und der lokale Titel-Filter.

Intern im Quellen-Paket, gehört nicht zum Interface `Source`.
"""

import html
import logging
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import httpx

from jobagent.job_ad import JobAd

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


class InvalidEntry(Exception):
    """Ein Pflichtfeld eines Eintrags hat den falschen Typ; nur dieser Eintrag fällt weg."""


def required_text(value: object) -> str:
    """Pflichtfeld (Titel, Link) als Text.

    Fehlt es (None), bleibt es "" wie bisher; jeder andere Typ als Text macht den
    Eintrag ungültig (InvalidEntry).
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidEntry
    return value


def text_or_none(value: object) -> str | None:
    """Optionales Feld (Firma, Ort, Beschreibung): Text bleibt, jeder andere Typ wird None."""
    return value if isinstance(value, str) else None


@dataclass(frozen=True, slots=True)
class ConvertedEntries:
    """Die Anzeigen aus den Einträgen einer Abfrage.

    `dropped` sagt, ob ein Eintrag wegen eines Pflichtfelds mit falschem Typ wegfiel.
    """

    job_ads: list[JobAd]
    dropped: bool

    def errors(self, subject: str) -> list[str]:
        """Fehler für den Quellenstatus: einmal "ungültige Antwort", falls ein Eintrag wegfiel."""
        return [f"{subject}: {INVALID_RESPONSE}"] if self.dropped else []


def convert_entries(
    entries: Iterable[dict], convert: Callable[[dict], JobAd], *, what: str, where: str
) -> ConvertedEntries:
    """Wandelt Einträge in Anzeigen um und lässt die mit falschem Typ im Pflichtfeld weg."""
    job_ads: list[JobAd] = []
    dropped = False
    for entry in entries:
        try:
            job_ads.append(convert(entry))
        except InvalidEntry:
            logger.error("%s: Eintrag mit falschem Typ im Pflichtfeld verworfen (%s)", what, where)
            dropped = True
    return ConvertedEntries(job_ads, dropped)


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
