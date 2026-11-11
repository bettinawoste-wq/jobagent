"""Anzeigen von Jobquellen holen (Bundesagentur, Arbeitnow, Firmen-Watchlist)."""

import base64
import html
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from jobagent.job_ad import JobAd

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
_DETAILS_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}"
_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
_TIMEOUT = 30.0

_ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
_ARBEITNOW_MAX_SEITEN = 10
_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")

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


def search(
    was: str,
    wo: str | None = None,
    umkreis: int | None = None,
    veroeffentlichtseit: int | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Suchergebnis:
    """Durchsucht die Jobsuche-API der Bundesagentur fuer Arbeit.

    Holt zu jedem Treffer zusaetzlich die Jobdetails, um die Beschreibung
    zu befuellen. Schlaegt der Detail-Call fuer eine einzelne Anzeige fehl,
    bleibt nur deren Beschreibung leer statt den gesamten Lauf abzubrechen.
    Netzwerk- oder API-Fehler der Suche selbst werden geloggt und im
    Suchergebnis gemeldet.
    """
    params: dict[str, str | int] = {"was": was}
    if wo is not None:
        params["wo"] = wo
    if umkreis is not None:
        params["umkreis"] = umkreis
    if veroeffentlichtseit is not None:
        params["veroeffentlichtseit"] = veroeffentlichtseit

    with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
        try:
            response = client.get(_SEARCH_URL, params=params, headers=_HEADERS)
            response.raise_for_status()
            daten = response.json()
        except httpx.HTTPError as fehler:
            logger.exception("Jobsuche-API-Anfrage fehlgeschlagen (was=%r, wo=%r)", was, wo)
            return Suchergebnis([], [f"{was}: {_grund(fehler)}"])
        except ValueError as fehler:
            logger.exception("Jobsuche-API-Antwort ist kein gueltiges JSON")
            return Suchergebnis([], [f"{was}: {_grund(fehler)}"])

        return Suchergebnis(
            [_zu_anzeige(eintrag, client) for eintrag in daten.get("ergebnisliste", [])]
        )


def _zu_anzeige(eintrag: dict, client: httpx.Client) -> JobAd:
    # Hinweis: Die Live-API liefert ein anderes Schema als die Doku von
    # bundesAPI/jobsuche-api (dort z.B. "stellenangebote"/"refnr"/"arbeitsort"/
    # "externeUrl"). Feldnamen hier sind gegen echte API-Antworten verifiziert.
    refnr = eintrag["referenznummer"]
    lokationen = eintrag.get("stellenlokationen") or [{}]
    adresse = lokationen[0].get("adresse") or {}
    link = eintrag.get("externeURL") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
    return JobAd(
        id=refnr,
        titel=eintrag.get("stellenangebotsTitel") or eintrag.get("hauptberuf", ""),
        firma=eintrag.get("firma"),
        ort=adresse.get("ort"),
        link=link,
        beschreibung=_hole_beschreibung(client, refnr),
    )


def _hole_beschreibung(client: httpx.Client, refnr: str) -> str | None:
    code = base64.b64encode(refnr.encode()).decode()
    url = _DETAILS_URL.format(code=code)
    try:
        response = client.get(url, headers=_HEADERS)
        response.raise_for_status()
        details = response.json()
    except httpx.HTTPError:
        logger.exception("Jobdetails-Anfrage fehlgeschlagen (refnr=%r)", refnr)
        return None
    except ValueError:
        logger.exception("Jobdetails-Antwort ist kein gueltiges JSON (refnr=%r)", refnr)
        return None

    return details.get("stellenangebotsBeschreibung") or details.get("stellenbeschreibung")


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
        titel=eintrag.get("title", ""),
        firma=eintrag.get("company_name"),
        ort=eintrag.get("location"),
        link=eintrag.get("url", ""),
        beschreibung=_html_zu_text(eintrag.get("description")),
    )


def _html_zu_text(markup: str | None) -> str | None:
    # Entschachtelt vor dem Tag-Strip, da Greenhouse HTML doppelt escaped
    # liefert ("&lt;div&gt;..." statt "<div>..."); fuer einfach escapte
    # Quellen (z.B. Arbeitnow) ist der erste unescape-Aufruf ein No-Op.
    if not markup:
        return None
    entschachtelt = html.unescape(markup)
    ohne_tags = _TAG_PATTERN.sub(" ", entschachtelt)
    text = html.unescape(ohne_tags)
    bereinigt = _WHITESPACE_PATTERN.sub(" ", text).strip()
    return bereinigt or None


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
        titel=eintrag.get("title", ""),
        firma=eintrag.get("company_name"),
        ort=(eintrag.get("location") or {}).get("name"),
        link=eintrag.get("absolute_url", ""),
        beschreibung=_hole_greenhouse_beschreibung(client, board_token, job_id),
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

    return _html_zu_text(details.get("content"))


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
        titel=eintrag.get("text", ""),
        firma=firma_name,
        ort=(eintrag.get("categories") or {}).get("location"),
        link=eintrag.get("hostedUrl", ""),
        beschreibung=eintrag.get("descriptionPlain"),
    )
