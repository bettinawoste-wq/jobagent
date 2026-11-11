"""Quellen: Adapter am Seam `Source`, über die der Lauf Anzeigen holt (siehe GLOSSARY.md)."""

from dataclasses import dataclass, field
from typing import Protocol

from jobagent.job_ad import JobAd


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Gefundene Anzeigen plus Fehler: leer und gescheitert sind verschiedene Dinge.

    Fehler haben die Form "<Suchbegriff oder Firma>: <Grund>".
    """

    job_ads: list[JobAd]
    errors: list[str] = field(default_factory=list)


class Source(Protocol):
    """Eine Quelle: sucht mit allen Suchbegriffen eines Laufs auf einmal und wirft nie."""

    @property
    def name(self) -> str:
        """Name im Quellenstatus des Reports."""
        ...

    def search(self, keywords: list[str]) -> SearchResult:
        """Liefert jede gefundene Anzeige einmal; Fehler stehen im Ergebnis."""
        ...
