"""Quelle Bundesagentur für Arbeit: Jobsuche-API (siehe CLAUDE.md, Quelle 1)."""

import base64
from dataclasses import replace

import httpx

from jobagent.job_ad import JobAd
from jobagent.sources import SearchResult
from jobagent.sources._http import (
    TIMEOUT,
    ConvertedEntries,
    FetchError,
    InvalidEntry,
    convert_entries,
    entries_with_ids,
    get_json,
    malformed_as_invalid,
    required_text,
    text_at,
    text_or_none,
)

_SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
_DETAILS_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}"
_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}


class BundesagenturSource:
    """Sucht je Suchbegriff in der Jobsuche-API und holt die Jobdetails je Anzeige einmal.

    Scheitert der Detail-Call einer Anzeige, bleibt nur deren Beschreibung leer; das gilt
    nicht als Fehler der Quelle.
    """

    name = "Bundesagentur für Arbeit"

    def __init__(
        self,
        location: str | None = None,
        radius: int | None = None,
        published_since: int | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._location = location
        self._radius = radius
        self._published_since = published_since
        self._transport = transport

    def search(self, keywords: list[str]) -> SearchResult:
        found: dict[str, JobAd] = {}
        errors: list[str] = []
        with httpx.Client(timeout=TIMEOUT, transport=self._transport) as client:
            for keyword in keywords:
                try:
                    converted = self._search_one(client, keyword)
                except FetchError as error:
                    errors.append(f"{keyword}: {error.reason}")
                    continue
                for job_ad in converted.job_ads:
                    found.setdefault(job_ad.id, job_ad)
                errors.extend(converted.errors(keyword))
            # Die Details erst nach dem Zusammenführen holen: je Anzeige nur einmal.
            job_ads = [
                replace(job_ad, description=_description(client, job_ad.id))
                for job_ad in found.values()
            ]
        return SearchResult(job_ads, errors)

    def _search_one(self, client: httpx.Client, keyword: str) -> ConvertedEntries:
        """Die Anzeigen zu einem Suchbegriff, noch ohne Beschreibung."""
        params: dict[str, str | int] = {"was": keyword}
        if self._location is not None:
            params["wo"] = self._location
        if self._radius is not None:
            params["umkreis"] = self._radius
        if self._published_since is not None:
            params["veroeffentlichtseit"] = self._published_since

        data = get_json(client, _SEARCH_URL, params=params, headers=_HEADERS)
        # Hinweis: Die Live-API liefert ein anderes Schema als die Doku von
        # bundesAPI/jobsuche-api (dort z.B. "stellenangebote"/"refnr"/"arbeitsort"/
        # "externeUrl"). Feldnamen hier sind gegen echte API-Antworten verifiziert.
        entries = entries_with_ids(
            data.get("ergebnisliste", []) if isinstance(data, dict) else None,
            "referenznummer",
            id_type=str,
            what="Jobsuche-Antwort",
            where=f"was={keyword!r}",
        )
        with malformed_as_invalid("Jobsuche-Antwort", f"was={keyword!r}"):
            return convert_entries(
                entries, _to_job_ad, what="Jobsuche-Antwort", where=f"was={keyword!r}"
            )


def _to_job_ad(entry: dict) -> JobAd:
    reference = entry["referenznummer"]
    # Ein Link mit falschem Typ zählt wie ein fehlender, dann greift der Ersatz.
    link = (
        text_or_none(entry.get("externeURL"))
        or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}"
    )
    return JobAd(
        id=reference,
        title=_title(entry),
        company=text_or_none(entry.get("firma")),
        location=text_at(entry, "stellenlokationen", 0, "adresse", "ort"),
        link=link,
    )


def _title(entry: dict) -> str:
    """Titel aus `stellenangebotsTitel`, sonst aus dem Ersatz `hauptberuf`.

    Ein Titel mit falschem Typ zählt wie ein fehlender. Bleibt danach kein Titel übrig,
    ist der Eintrag ungültig, statt still ohne Titel im Report zu landen.
    """
    raw = entry.get("stellenangebotsTitel")
    title = text_or_none(raw) or required_text(entry.get("hauptberuf"))
    if not title and raw is not None and not isinstance(raw, str):
        raise InvalidEntry
    return title


def _description(client: httpx.Client, reference: str) -> str | None:
    code = base64.b64encode(reference.encode()).decode()
    try:
        details = get_json(client, _DETAILS_URL.format(code=code), headers=_HEADERS)
    except FetchError:
        return None
    if not isinstance(details, dict):
        return None
    return text_or_none(details.get("stellenangebotsBeschreibung")) or text_or_none(
        details.get("stellenbeschreibung")
    )
