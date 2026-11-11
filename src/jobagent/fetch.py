"""Reste der alten Quellen: nur noch Typen fuer Lauf, Report und Uebergangsadapter.

Alle Quellen sind Adapter in `sources`; was hier steht, raeumt #15 weg.
"""

from dataclasses import dataclass, field

from jobagent.job_ad import JobAd


@dataclass(frozen=True, slots=True)
class Suchergebnis:
    """Gefundene Anzeigen plus Fehler: leer und gescheitert sind verschiedene Dinge."""

    job_ads: list[JobAd]
    fehler: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Quellenstatus:
    name: str
    anzahl: int
    fehler: list[str]
