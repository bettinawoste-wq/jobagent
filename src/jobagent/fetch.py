"""Anzeigen von Jobquellen holen (Arbeitnow).

Uebergangsweise: Bundesagentur und Firmen-Watchlist sind schon Adapter in `sources`.
"""

import logging
import time
from dataclasses import dataclass, field

import httpx

from jobagent.job_ad import JobAd
from jobagent.sources._http import html_to_text

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0

_ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
_ARBEITNOW_MAX_SEITEN = 10

_UNGUELTIGE_ANTWORT = "ungültige Antwort"


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


def _grund(fehler: Exception) -> str:
    if isinstance(fehler, httpx.HTTPStatusError):
        return f"HTTP {fehler.response.status_code}"
    if isinstance(fehler, httpx.HTTPError):
        return "keine Verbindung"
    return _UNGUELTIGE_ANTWORT


def search_arbeitnow(
    was: str,
    wo: str | None = None,
    veroeffentlichtseit: int | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Suchergebnis:
    """Durchsucht die kostenlose Arbeitnow-API (kein API-Key noetig).

    Die API bietet keine serverseitige Stichwort- oder Ortssuche, daher wird
    clientseitig nach Titel (was) und Ort (wo) gefiltert. umkreis wird nicht
    unterstuetzt, da keine Geokoordinaten verfuegbar sind. Ergebnisse sind
    nach Veroeffentlichung sortiert; das Paging stoppt, sobald ein Eintrag
    aelter als veroeffentlichtseit Tage auftaucht (max. 10 Seiten als
    Sicherheitsgrenze, auch ohne Datumsfilter - Arbeitnow bittet explizit
    um massvolle Nutzung der freien API).
    """
    grenze = time.time() - veroeffentlichtseit * 86400 if veroeffentlichtseit is not None else None

    treffer: list[JobAd] = []
    url: str | None = _ARBEITNOW_URL
    with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
        for _ in range(_ARBEITNOW_MAX_SEITEN):
            if not url:
                break
            try:
                response = client.get(url)
                response.raise_for_status()
                daten = response.json()
            except httpx.HTTPError as fehler:
                logger.exception("Arbeitnow-API-Anfrage fehlgeschlagen (was=%r, wo=%r)", was, wo)
                return Suchergebnis(treffer, [f"{was}: {_grund(fehler)}"])
            except ValueError as fehler:
                logger.exception("Arbeitnow-API-Antwort ist kein gueltiges JSON")
                return Suchergebnis(treffer, [f"{was}: {_grund(fehler)}"])

            eintraege = daten.get("data", [])
            if not eintraege:
                break

            zu_alt_erreicht = False
            for eintrag in eintraege:
                erstellt = eintrag.get("created_at")
                if grenze is not None and isinstance(erstellt, int | float) and erstellt < grenze:
                    zu_alt_erreicht = True
                    continue
                if _arbeitnow_passt(eintrag, was, wo):
                    treffer.append(_arbeitnow_zu_anzeige(eintrag))

            if zu_alt_erreicht:
                break
            url = (daten.get("links") or {}).get("next")

    return Suchergebnis(treffer)


def _arbeitnow_passt(eintrag: dict, was: str, wo: str | None) -> bool:
    titel = eintrag.get("title", "")
    if was and was.lower() not in titel.lower():
        return False
    if wo:
        ort = eintrag.get("location") or ""
        if wo.lower() not in ort.lower():
            return False
    return True


def _arbeitnow_zu_anzeige(eintrag: dict) -> JobAd:
    return JobAd(
        id=f"arbeitnow:{eintrag['slug']}",
        title=eintrag.get("title", ""),
        company=eintrag.get("company_name"),
        location=eintrag.get("location"),
        link=eintrag.get("url", ""),
        description=html_to_text(eintrag.get("description")),
    )
