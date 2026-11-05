"""Anzeigen von Jobquellen holen (Bundesagentur fuer Arbeit, Arbeitnow)."""

import base64
import html
import logging
import re
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
_DETAILS_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}"
_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
_TIMEOUT = 30.0

_ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
_ARBEITNOW_MAX_SEITEN = 10
_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Anzeige:
    id: str
    titel: str
    firma: str | None
    ort: str | None
    link: str
    beschreibung: str | None = None


def search(
    was: str,
    wo: str | None = None,
    umkreis: int | None = None,
    veroeffentlichtseit: int | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> list[Anzeige]:
    """Durchsucht die Jobsuche-API der Bundesagentur fuer Arbeit.

    Holt zu jedem Treffer zusaetzlich die Jobdetails, um die Beschreibung
    zu befuellen. Schlaegt der Detail-Call fuer eine einzelne Anzeige fehl,
    bleibt nur deren Beschreibung leer statt den gesamten Lauf abzubrechen.
    Bei Netzwerk- oder API-Fehlern der Suche selbst wird eine leere Liste
    zurueckgegeben und der Fehler geloggt.
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
        except httpx.HTTPError:
            logger.exception("Jobsuche-API-Anfrage fehlgeschlagen (was=%r, wo=%r)", was, wo)
            return []
        except ValueError:
            logger.exception("Jobsuche-API-Antwort ist kein gueltiges JSON")
            return []

        return [_zu_anzeige(eintrag, client) for eintrag in daten.get("ergebnisliste", [])]


def _zu_anzeige(eintrag: dict, client: httpx.Client) -> Anzeige:
    # Hinweis: Die Live-API liefert ein anderes Schema als die Doku von
    # bundesAPI/jobsuche-api (dort z.B. "stellenangebote"/"refnr"/"arbeitsort"/
    # "externeUrl"). Feldnamen hier sind gegen echte API-Antworten verifiziert.
    refnr = eintrag["referenznummer"]
    lokationen = eintrag.get("stellenlokationen") or [{}]
    adresse = lokationen[0].get("adresse") or {}
    link = eintrag.get("externeURL") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
    return Anzeige(
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
) -> list[Anzeige]:
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

    treffer: list[Anzeige] = []
    url: str | None = _ARBEITNOW_URL
    with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
        for _ in range(_ARBEITNOW_MAX_SEITEN):
            if not url:
                break
            try:
                response = client.get(url)
                response.raise_for_status()
                daten = response.json()
            except httpx.HTTPError:
                logger.exception("Arbeitnow-API-Anfrage fehlgeschlagen (was=%r, wo=%r)", was, wo)
                return treffer
            except ValueError:
                logger.exception("Arbeitnow-API-Antwort ist kein gueltiges JSON")
                return treffer

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

    return treffer


def _arbeitnow_passt(eintrag: dict, was: str, wo: str | None) -> bool:
    titel = eintrag.get("title", "")
    if was and was.lower() not in titel.lower():
        return False
    if wo:
        ort = eintrag.get("location") or ""
        if wo.lower() not in ort.lower():
            return False
    return True


def _arbeitnow_zu_anzeige(eintrag: dict) -> Anzeige:
    return Anzeige(
        id=f"arbeitnow:{eintrag['slug']}",
        titel=eintrag.get("title", ""),
        firma=eintrag.get("company_name"),
        ort=eintrag.get("location"),
        link=eintrag.get("url", ""),
        beschreibung=_html_zu_text(eintrag.get("description")),
    )


def _html_zu_text(markup: str | None) -> str | None:
    if not markup:
        return None
    ohne_tags = _TAG_PATTERN.sub(" ", markup)
    text = html.unescape(ohne_tags)
    bereinigt = _WHITESPACE_PATTERN.sub(" ", text).strip()
    return bereinigt or None
