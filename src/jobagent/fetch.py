"""Anzeigen von Jobquellen holen (Firmen-Watchlist).

Uebergangsweise: Bundesagentur und Arbeitnow sind schon Adapter in `sources`.
"""

import logging
from dataclasses import dataclass, field

import httpx

from jobagent.job_ad import JobAd
from jobagent.sources._http import html_to_text

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0

_GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
_GREENHOUSE_DETAIL_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
_LEVER_URL = "https://api.lever.co/v0/postings/{company_slug}"

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


def search_watchlist(
    firmen: list[dict],
    was: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Suchergebnis:
    """Durchsucht die oeffentlichen Jobboards konkret beobachteter Firmen.

    Jeder Eintrag in firmen braucht die Felder "name", "ats" ("greenhouse"
    oder "lever") und "slug" (Board-Token bzw. Firmen-Slug). Scheitert eine
    einzelne Firma (falscher Slug, API-Fehler), wird das geloggt, mit dem
    Firmennamen gemeldet und die uebrigen Firmen trotzdem durchsucht.
    """
    treffer: list[JobAd] = []
    fehler: list[str] = []
    for firma in firmen:
        ats = firma.get("ats")
        slug = firma.get("slug")
        name = firma.get("name", slug)
        if ats == "greenhouse":
            ergebnis = search_greenhouse(slug, was, transport=transport)
        elif ats == "lever":
            ergebnis = search_lever(slug, name, was, transport=transport)
        else:
            logger.error("Unbekannter ats-Typ in Watchlist: %r (firma=%r)", ats, name)
            fehler.append(f"{name}: unbekannter ats-Typ")
            continue
        treffer.extend(ergebnis.job_ads)
        fehler.extend(f"{name}: {grund}" for grund in ergebnis.fehler)
    return Suchergebnis(treffer, fehler)


def search_greenhouse(
    board_token: str,
    was: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Suchergebnis:
    """Durchsucht das oeffentliche Greenhouse-Jobboard einer einzelnen Firma.

    Keine serverseitige Stichwortsuche - Filterung nach Titel (was) passiert
    clientseitig. Holt die volle Beschreibung pro Treffer per Detail-Call;
    schlaegt dieser fehl, bleibt nur dessen Beschreibung leer statt den
    gesamten Firmen-Durchlauf abzubrechen.
    """
    url = _GREENHOUSE_URL.format(board_token=board_token)
    with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
        try:
            response = client.get(url)
            response.raise_for_status()
            daten = response.json()
        except httpx.HTTPError as fehler:
            logger.exception("Greenhouse-Anfrage fehlgeschlagen (board=%r)", board_token)
            return Suchergebnis([], [_grund(fehler)])
        except ValueError as fehler:
            logger.exception("Greenhouse-Antwort ist kein gueltiges JSON (board=%r)", board_token)
            return Suchergebnis([], [_grund(fehler)])

        return Suchergebnis(
            [
                _greenhouse_zu_anzeige(eintrag, board_token, client)
                for eintrag in daten.get("jobs", [])
                if was.lower() in eintrag.get("title", "").lower()
            ]
        )


def _greenhouse_zu_anzeige(eintrag: dict, board_token: str, client: httpx.Client) -> JobAd:
    job_id = eintrag["id"]
    return JobAd(
        id=f"greenhouse:{board_token}:{job_id}",
        title=eintrag.get("title", ""),
        company=eintrag.get("company_name"),
        location=(eintrag.get("location") or {}).get("name"),
        link=eintrag.get("absolute_url", ""),
        description=_hole_greenhouse_beschreibung(client, board_token, job_id),
    )


def _hole_greenhouse_beschreibung(
    client: httpx.Client, board_token: str, job_id: int
) -> str | None:
    url = _GREENHOUSE_DETAIL_URL.format(board_token=board_token, job_id=job_id)
    try:
        response = client.get(url, params={"content": "true"})
        response.raise_for_status()
        details = response.json()
    except httpx.HTTPError:
        logger.exception(
            "Greenhouse-Detail-Anfrage fehlgeschlagen (board=%r, job_id=%r)", board_token, job_id
        )
        return None
    except ValueError:
        logger.exception(
            "Greenhouse-Detail-Antwort ist kein gueltiges JSON (board=%r, job_id=%r)",
            board_token,
            job_id,
        )
        return None

    return html_to_text(details.get("content"))


def search_lever(
    company_slug: str,
    firma_name: str,
    was: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Suchergebnis:
    """Durchsucht die oeffentlichen Lever-Postings einer einzelnen Firma.

    Keine serverseitige Stichwortsuche - Filterung nach Titel (was) passiert
    clientseitig. Lever liefert bereits eine reine Textbeschreibung
    (descriptionPlain), kein HTML-Stripping noetig.
    """
    url = _LEVER_URL.format(company_slug=company_slug)
    with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
        try:
            response = client.get(url, params={"mode": "json"})
            response.raise_for_status()
            daten = response.json()
        except httpx.HTTPError as fehler:
            logger.exception("Lever-Anfrage fehlgeschlagen (firma=%r)", company_slug)
            return Suchergebnis([], [_grund(fehler)])
        except ValueError as fehler:
            logger.exception("Lever-Antwort ist kein gueltiges JSON (firma=%r)", company_slug)
            return Suchergebnis([], [_grund(fehler)])

    if not isinstance(daten, list):
        logger.error("Lever-Antwort hat unerwartetes Format (firma=%r): %r", company_slug, daten)
        return Suchergebnis([], [_UNGUELTIGE_ANTWORT])

    return Suchergebnis(
        [
            _lever_zu_anzeige(eintrag, company_slug, firma_name)
            for eintrag in daten
            if was.lower() in eintrag.get("text", "").lower()
        ]
    )


def _lever_zu_anzeige(eintrag: dict, company_slug: str, firma_name: str) -> JobAd:
    return JobAd(
        id=f"lever:{company_slug}:{eintrag['id']}",
        title=eintrag.get("text", ""),
        company=firma_name,
        location=(eintrag.get("categories") or {}).get("location"),
        link=eintrag.get("hostedUrl", ""),
        description=eintrag.get("descriptionPlain"),
    )
