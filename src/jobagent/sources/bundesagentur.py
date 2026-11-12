"""Quelle Bundesagentur für Arbeit: Jobsuche-API (siehe CLAUDE.md, Quelle 1)."""

import base64
from dataclasses import replace

import httpx

from jobagent.job_ad import JobAd
from jobagent.sources import SearchResult
from jobagent.sources._http import (
    TIMEOUT,
    FetchError,
    entries_with_ids,
    get_json,
    malformed_as_invalid,
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
                    for job_ad in self._search_one(client, keyword):
                        found.setdefault(job_ad.id, job_ad)
                except FetchError as error:
                    errors.append(f"{keyword}: {error.reason}")
            # Die Details erst nach dem Zusammenführen holen: je Anzeige nur einmal.
            job_ads = [
                replace(job_ad, description=_description(client, job_ad.id))
                for job_ad in found.values()
            ]
        return SearchResult(job_ads, errors)

    def _search_one(self, client: httpx.Client, keyword: str) -> list[JobAd]:
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
            return [_to_job_ad(entry) for entry in entries]


def _to_job_ad(entry: dict) -> JobAd:
    reference = entry["referenznummer"]
    locations = entry.get("stellenlokationen") or [{}]
    address = locations[0].get("adresse") or {}
    link = (
        entry.get("externeURL") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}"
    )
    return JobAd(
        id=reference,
        title=entry.get("stellenangebotsTitel") or entry.get("hauptberuf", ""),
        company=entry.get("firma"),
        location=address.get("ort"),
        link=link,
    )


def _description(client: httpx.Client, reference: str) -> str | None:
    code = base64.b64encode(reference.encode()).decode()
    try:
        details = get_json(client, _DETAILS_URL.format(code=code), headers=_HEADERS)
    except FetchError:
        return None
    if not isinstance(details, dict):
        return None
    return details.get("stellenangebotsBeschreibung") or details.get("stellenbeschreibung")
