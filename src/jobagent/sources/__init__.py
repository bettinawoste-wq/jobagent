"""Quellen: Adapter am Seam `Source`, über die der Lauf Anzeigen holt (siehe GLOSSARY.md)."""

from dataclasses import dataclass, field
from typing import Protocol

from jobagent.job_ad import JobAd


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Gefundene Anzeigen plus Fehler: leer und gescheitert sind verschiedene Dinge.

    Fehler haben die Form "<Suchbegriff oder Firma>: <Grund>". Hinweise (`notices`) sind
    keine Fehler, etwa eine bekannte Grenze der Schnittstelle; ein Lauf mit Hinweisen kann
    vollständig sein.
    """

    job_ads: list[JobAd]
    errors: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)


class DescriptionUnavailable(Exception):
    """Die Beschreibung einer Anzeige ließ sich nicht abrufen; `reason` ist der Grund.

    Die Anzeige bleibt dann unbewertet und kommt im nächsten Lauf wieder.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Source(Protocol):
    """Eine Quelle: sucht mit allen Suchbegriffen eines Laufs auf einmal.

    `search` wirft nie. Die Beschreibung einer Anzeige holt der Lauf erst über `describe`,
    und nur für neue Anzeigen: Quellen mit teurem Detail-Abruf sparen so die Abrufe für
    schon gemerkte Anzeigen (ADR 0002).
    """

    @property
    def name(self) -> str:
        """Name im Quellenstatus des Reports."""
        ...

    def search(self, keywords: list[str]) -> SearchResult:
        """Liefert jede gefundene Anzeige einmal; Fehler stehen im Ergebnis."""
        ...

    def describe(self, job_ad: JobAd) -> JobAd:
        """Die Anzeige mit Beschreibung; hat sie sie schon aus `search`, unverändert.

        Antwortet die Quelle ohne Beschreibung, bleibt sie None. Scheitert der Abruf selbst,
        wirft sie `DescriptionUnavailable`.
        """
        ...
