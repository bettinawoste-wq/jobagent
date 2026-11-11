"""Übergangsadapter: hängt die alten Suchfunktionen aus `fetch` an den Seam `Source`.

Nur bis Arbeitnow und die Firmen-Watchlist eigene Adapter haben (#13, #14).
"""

from collections.abc import Callable

from jobagent import fetch
from jobagent.job_ad import JobAd
from jobagent.sources import SearchResult


class LegacySource:
    """Ruft eine alte Suchfunktion je Suchbegriff auf und dedupliziert das Ergebnis."""

    def __init__(self, name: str, search_one: Callable[[str], fetch.Suchergebnis]) -> None:
        self.name = name
        self._search_one = search_one

    def search(self, keywords: list[str]) -> SearchResult:
        job_ads: dict[str, JobAd] = {}
        errors: dict[str, None] = {}  # dict statt set: Reihenfolge bleibt erhalten
        for keyword in keywords:
            result = self._search_one(keyword)
            errors.update(dict.fromkeys(result.fehler))
            for job_ad in result.job_ads:
                job_ads.setdefault(job_ad.id, job_ad)
        return SearchResult(list(job_ads.values()), list(errors))
