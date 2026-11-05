"""Anzeigen von Jobquellen holen (zuerst nur Bundesagentur fuer Arbeit)."""

import base64
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
_DETAILS_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}"
_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
_TIMEOUT = 30.0


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
