"""Quelle Arbeitnow: kostenlose Job-Board-API ohne Key (siehe CLAUDE.md, Quelle 2)."""

import time
from collections.abc import Callable, Iterator

import httpx

from jobagent.job_ad import JobAd
from jobagent.sources import SearchResult
from jobagent.sources._http import (
    TIMEOUT,
    FetchError,
    entries_with_ids,
    get_json,
    html_to_text,
    title_matches,
)

_URL = "https://www.arbeitnow.com/api/job-board-api"
# Arbeitnow bittet um maßvolle Nutzung der freien API (ADR 0002).
_MAX_PAGES = 10


class ArbeitnowSource:
    """Blättert pro Lauf einmal durch die neuesten Anzeigen und filtert lokal.

    Die API kennt weder Stichwort- noch Ortssuche, daher werden alle Suchbegriffe und
    der Ort clientseitig auf Titel bzw. Ort angewandt; einen Umkreis gibt es mangels
    Geokoordinaten nicht. Das Paging folgt `links.next`, endet nach höchstens 10 Seiten
    oder nach der Seite, auf der Anzeigen älter als `published_since` Tage auftauchen.
    Bricht es ab, bleiben die bis dahin gefundenen Anzeigen erhalten.
    """

    name = "Arbeitnow"

    def __init__(
        self,
        location: str | None = None,
        published_since: int | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._location = location
        self._published_since = published_since
        self._transport = transport
        self._now = now

    def search(self, keywords: list[str]) -> SearchResult:
        if not keywords:
            return SearchResult([])
        job_ads: dict[str, JobAd] = {}
        try:
            for entry in self._recent_entries():
                if self._matches(entry, keywords):
                    job_ad = _to_job_ad(entry)
                    job_ads.setdefault(job_ad.id, job_ad)
        except FetchError as error:
            # Ein Abruf dient allen Suchbegriffen, daher nennt der Fehler sie alle.
            return SearchResult(list(job_ads.values()), [f"{', '.join(keywords)}: {error.reason}"])
        return SearchResult(list(job_ads.values()))

    def _recent_entries(self) -> Iterator[dict]:
        """Liefert die Einträge Seite für Seite, solange sie jung genug sind."""
        cutoff = (
            self._now() - self._published_since * 86400
            if self._published_since is not None
            else None
        )
        url: str | None = _URL
        with httpx.Client(timeout=TIMEOUT, transport=self._transport) as client:
            for _ in range(_MAX_PAGES):
                if not url:
                    return
                data = get_json(client, url)
                entries = entries_with_ids(
                    data.get("data") if isinstance(data, dict) else None,
                    "slug",
                    what="Arbeitnow-Antwort",
                    where=f"url={url!r}",
                )
                if not entries:
                    return

                too_old_reached = False
                for entry in entries:
                    created_at = entry.get("created_at")
                    if cutoff is not None and isinstance(created_at, int | float):
                        if created_at < cutoff:
                            too_old_reached = True
                            continue
                    yield entry
                if too_old_reached:
                    return
                url = (data.get("links") or {}).get("next")

    def _matches(self, entry: dict, keywords: list[str]) -> bool:
        if not title_matches(entry.get("title"), keywords):
            return False
        if self._location:
            return self._location.lower() in (entry.get("location") or "").lower()
        return True


def _to_job_ad(entry: dict) -> JobAd:
    return JobAd(
        id=f"arbeitnow:{entry['slug']}",
        title=entry.get("title", ""),
        company=entry.get("company_name"),
        location=entry.get("location"),
        link=entry.get("url", ""),
        description=html_to_text(entry.get("description")),
    )
