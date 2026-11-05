"""Anzeigen von Jobquellen holen (zuerst nur Bundesagentur fuer Arbeit)."""

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
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

    Gibt bei Netzwerk- oder API-Fehlern eine leere Liste zurueck und loggt
    den Fehler, damit eine fehlerhafte Quelle den Gesamtlauf nicht abbricht.
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

    return [_zu_anzeige(eintrag) for eintrag in daten.get("stellenangebote", [])]


def _zu_anzeige(eintrag: dict) -> Anzeige:
    refnr = eintrag["refnr"]
    arbeitsort = eintrag.get("arbeitsort") or {}
    link = eintrag.get("externeUrl") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
    return Anzeige(
        id=refnr,
        titel=eintrag.get("beruf", ""),
        firma=eintrag.get("arbeitgeber"),
        ort=arbeitsort.get("ort"),
        link=link,
    )
