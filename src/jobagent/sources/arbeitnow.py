"""Quelle Arbeitnow: kostenlose Job-Board-API ohne Key (siehe CLAUDE.md, Quelle 2)."""

import math
import time
from collections.abc import Callable, Iterator

import httpx

from jobagent.job_ad import JobAd
from jobagent.sources import SearchResult
from jobagent.sources._http import (
    TIMEOUT,
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
        matching: list[dict] = []
        fetch_reason: str | None = None
        try:
            with malformed_as_invalid("Arbeitnow-Antwort", f"url={_URL!r}"):
                for entry in self._recent_entries():
                    if self._matches(entry, keywords):
                        matching.append(entry)
        except FetchError as error:
            # Die Einträge der Seiten davor bleiben erhalten.
            fetch_reason = error.reason
        converted = convert_entries(
            matching, _to_job_ad, what="Arbeitnow-Antwort", where=f"url={_URL!r}"
        )
        job_ads: dict[str, JobAd] = {}
        for job_ad in converted.job_ads:
            job_ads.setdefault(job_ad.id, job_ad)
        # Ein Abruf dient allen Suchbegriffen, daher nennt jeder Fehler sie alle.
        subject = ", ".join(keywords)
        errors = converted.errors(subject)
        if fetch_reason is not None and f"{subject}: {fetch_reason}" not in errors:
            errors.append(f"{subject}: {fetch_reason}")
        return SearchResult(list(job_ads.values()), errors)

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
                    created_at = _timestamp(entry.get("created_at"))
                    if cutoff is not None and created_at is not None:
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
            return self._location.lower() in (text_at(entry, "location") or "").lower()
        return True


def _timestamp(value: object) -> float | None:
    """Veröffentlichungsdatum als Zeitstempel.

    Ein Wahrheitswert ist keiner (bool ist ein int), eine nicht endliche Zahl wie NaN
    oder Infinity auch nicht (json.loads liest beide).
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    # Nur Gleitkommazahlen prüfen: math.isfinite wirft bei sehr langen Ganzzahlen.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _to_job_ad(entry: dict) -> JobAd:
    return JobAd(
        id=f"arbeitnow:{entry['slug']}",
        title=required_text(entry.get("title")),
        company=text_or_none(entry.get("company_name")),
        location=text_at(entry, "location"),
        link=required_text(entry.get("url")),
        description=html_to_text(entry.get("description")),
    )
