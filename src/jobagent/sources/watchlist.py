"""Quelle Firmen-Watchlist: öffentliche Jobboards bei Greenhouse und Lever (CLAUDE.md, Quelle 3)."""

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from jobagent.job_ad import JobAd
from jobagent.sources import SearchResult
from jobagent.sources._http import (
    TIMEOUT,
    ConvertedEntries,
    FetchError,
    convert_entries,
    entries_with_ids,
    get_json,
    html_to_text,
    malformed_as_invalid,
    required_text,
    text_at,
    text_or_none,
    title_matches,
)

logger = logging.getLogger(__name__)

_GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
_GREENHOUSE_DETAILS_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
_LEVER_URL = "https://api.lever.co/v0/postings/{slug}"


@dataclass(frozen=True, slots=True)
class WatchlistCompany:
    """Eine beobachtete Firma; `ats` wählt den Jobboard-Anbieter ("greenhouse" oder "lever")."""

    name: str
    ats: str
    slug: str


class _Board(Protocol):
    def search(self, client: httpx.Client, keywords: list[str]) -> ConvertedEntries:
        """Fragt das Board einmal ab und liefert die passenden Anzeigen; wirft FetchError."""
        ...


class GreenhouseBoard:
    """Greenhouse-Board einer Firma; der Detail-Call kommt nur für Treffer."""

    def __init__(self, slug: str) -> None:
        self._slug = slug

    def search(self, client: httpx.Client, keywords: list[str]) -> ConvertedEntries:
        data = get_json(client, _GREENHOUSE_URL.format(slug=self._slug))
        jobs = entries_with_ids(
            data.get("jobs") if isinstance(data, dict) else None,
            "id",
            what="Greenhouse-Antwort",
            where=f"board={self._slug!r}",
        )
        where = f"board={self._slug!r}"
        with malformed_as_invalid("Greenhouse-Antwort", where):
            return convert_entries(
                (job for job in jobs if title_matches(job.get("title"), keywords)),
                lambda job: self._to_job_ad(client, job),
                what="Greenhouse-Antwort",
                where=where,
            )

    def _to_job_ad(self, client: httpx.Client, job: dict) -> JobAd:
        job_id = job["id"]
        title = required_text(job.get("title"))
        link = required_text(job.get("absolute_url"))
        # Erst nach den Pflichtfeldern: Ein ungültiger Eintrag kostet keinen Detail-Call.
        description = self._description(client, job_id)
        return JobAd(
            id=f"greenhouse:{self._slug}:{job_id}",
            title=title,
            company=text_or_none(job.get("company_name")),
            location=text_at(job, "location", "name"),
            link=link,
            description=description,
        )

    def _description(self, client: httpx.Client, job_id: object) -> str | None:
        # Scheitert der Detail-Call, bleibt nur die Beschreibung dieser Anzeige leer.
        url = _GREENHOUSE_DETAILS_URL.format(slug=self._slug, job_id=job_id)
        try:
            details = get_json(client, url, params={"content": "true"})
        except FetchError:
            return None
        if not isinstance(details, dict):
            return None
        return html_to_text(details.get("content"))


class LeverBoard:
    """Lever-Board einer Firma; Lever liefert die Beschreibung schon als reinen Text."""

    def __init__(self, slug: str, company_name: str) -> None:
        self._slug = slug
        self._company_name = company_name

    def search(self, client: httpx.Client, keywords: list[str]) -> ConvertedEntries:
        postings = get_json(client, _LEVER_URL.format(slug=self._slug), params={"mode": "json"})
        # Lever antwortet mit einer rohen Liste, nicht mit einem Wrapper-Objekt.
        postings = entries_with_ids(
            postings, "id", what="Lever-Antwort", where=f"board={self._slug!r}"
        )
        where = f"board={self._slug!r}"
        with malformed_as_invalid("Lever-Antwort", where):
            return convert_entries(
                (posting for posting in postings if title_matches(posting.get("text"), keywords)),
                self._to_job_ad,
                what="Lever-Antwort",
                where=where,
            )

    def _to_job_ad(self, posting: dict) -> JobAd:
        return JobAd(
            id=f"lever:{self._slug}:{posting['id']}",
            title=required_text(posting.get("text")),
            company=self._company_name,
            location=text_at(posting, "categories", "location"),
            link=required_text(posting.get("hostedUrl")),
            description=text_or_none(posting.get("descriptionPlain")),
        )


def _board(company: WatchlistCompany) -> _Board | None:
    if company.ats == "greenhouse":
        return GreenhouseBoard(company.slug)
    if company.ats == "lever":
        return LeverBoard(company.slug, company.name)
    return None


class WatchlistSource:
    """Durchsucht die Jobboards konkret beobachteter Firmen, jedes Board einmal pro Lauf.

    Scheitert eine Firma (falscher Slug, API-Fehler, unbekannter ats-Typ), steht sie mit
    Namen in den Fehlern, und die übrigen Firmen werden trotzdem durchsucht.
    """

    name = "Firmen-Watchlist"

    def __init__(
        self,
        companies: list[WatchlistCompany],
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._companies = companies
        self._transport = transport

    def search(self, keywords: list[str]) -> SearchResult:
        job_ads: dict[str, JobAd] = {}
        errors: list[str] = []
        with httpx.Client(timeout=TIMEOUT, transport=self._transport) as client:
            for company in self._companies:
                board = _board(company)
                if board is None:
                    logger.error(
                        "Unbekannter ats-Typ in Watchlist: %r (firma=%r)", company.ats, company.name
                    )
                    errors.append(f"{company.name}: unbekannter ats-Typ")
                    continue
                try:
                    converted = board.search(client, keywords)
                except FetchError as error:
                    errors.append(f"{company.name}: {error.reason}")
                    continue
                except Exception:
                    # Eine Firma darf die übrigen nie kosten, auch nicht durch einen Fehler,
                    # den kein Board vorhergesehen hat.
                    logger.exception("Unerwarteter Fehler in Watchlist (firma=%r)", company.name)
                    errors.append(f"{company.name}: unerwarteter Fehler")
                    continue
                for job_ad in converted.job_ads:
                    job_ads.setdefault(job_ad.id, job_ad)
                errors.extend(converted.errors(company.name))
        return SearchResult(list(job_ads.values()), errors)
