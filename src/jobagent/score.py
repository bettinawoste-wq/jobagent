"""Bewertung einer Anzeige gegen profile.md via Anthropic API (Modell Haiku)."""

import logging
from dataclasses import dataclass

import anthropic

from jobagent.job_ad import JobAd

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 1024
_TOOL_NAME = "bewertung_abgeben"

_TOOL_SCHEMA = {
    "name": _TOOL_NAME,
    "description": "Gibt die Bewertung einer Stellenanzeige gegen das Suchprofil zurueck.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
            "passt": {"type": "array", "items": {"type": "string"}},
            "passt_nicht": {"type": "array", "items": {"type": "string"}},
            "luecken": {"type": "array", "items": {"type": "string"}},
            "kurzfazit": {
                "type": "string",
                "description": "Maximal ein kurzer Satz, keine Aufzaehlung von Gruenden.",
            },
        },
        "required": ["score", "passt", "passt_nicht", "luecken", "kurzfazit"],
    },
}

_SYSTEM_PROMPT = (
    "Du bewertest Stellenanzeigen gegen das Suchprofil einer Bewerberin. "
    f"Antworte ausschliesslich ueber das Werkzeug {_TOOL_NAME}. "
    "Score-Skala: 5 = sehr gute Passung, sofort bewerben; 4 = gute Passung, "
    "kleine Luecken; 3 = machbar, aber deutliche Luecken oder Abstriche; "
    "2 = eher nein; 1 = passt nicht. "
    "kurzfazit ist genau ein kurzer Satz (maximal 20 Woerter) mit der "
    "wichtigsten Begruendung fuer den Score - keine Aufzaehlung, keine "
    "Wiederholung von passt/passt_nicht/luecken. "
    "passt, passt_nicht und luecken sind JSON-Arrays aus einzelnen kurzen "
    "Punkten (je ein eigener String), niemals ein einzelner "
    "zusammengefasster Text mit Kommas."
)


@dataclass(frozen=True, slots=True)
class Assessment:
    score: int
    passt: list[str]
    passt_nicht: list[str]
    luecken: list[str]
    kurzfazit: str


def score_job_ad(
    job_ad: JobAd,
    profil: str,
    *,
    client: anthropic.Anthropic | None = None,
) -> Assessment | None:
    """Bewertet eine Anzeige gegen das Suchprofil mittels Claude Haiku.

    Gibt None zurueck und loggt, wenn die Anthropic-API nicht erreichbar ist
    oder eine ungueltige Antwort liefert, statt den Lauf abzubrechen.
    """
    aktiver_client = client or anthropic.Anthropic()

    nutzertext = f"Suchprofil:\n{profil}\n\nStellenanzeige:\n{_job_ad_as_text(job_ad)}"
    try:
        antwort = aktiver_client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": nutzertext}],
        )
    except (anthropic.AnthropicError, TypeError):
        # TypeError: die SDK wirft dies statt eines AnthropicError, wenn z.B.
        # kein ANTHROPIC_API_KEY gesetzt ist (Validierung beim Request-Aufbau).
        logger.exception("Anthropic-API-Anfrage fehlgeschlagen (anzeige=%r)", job_ad.id)
        return None

    return _to_assessment(antwort, job_ad.id)


def _job_ad_as_text(job_ad: JobAd) -> str:
    zeilen = [
        f"Titel: {job_ad.titel}",
        f"Firma: {job_ad.firma or 'unbekannt'}",
        f"Ort: {job_ad.ort or 'unbekannt'}",
    ]
    if job_ad.beschreibung:
        zeilen.append(f"Beschreibung: {job_ad.beschreibung}")
    return "\n".join(zeilen)


def _to_assessment(antwort: anthropic.types.Message, job_ad_id: str) -> Assessment | None:
    tool_use = next((block for block in antwort.content if block.type == "tool_use"), None)
    if tool_use is None:
        logger.error("Keine Tool-Antwort von Claude erhalten (anzeige=%r)", job_ad_id)
        return None

    try:
        return _validiere(tool_use.input)
    except (KeyError, TypeError, ValueError):
        logger.exception("Ungueltige Bewertungsantwort (anzeige=%r): %r", job_ad_id, tool_use.input)
        return None


def _validiere(daten: dict) -> Assessment:
    score = int(daten["score"])
    if not 1 <= score <= 5:
        raise ValueError(f"score ausserhalb 1-5: {score}")

    return Assessment(
        score=score,
        passt=_als_string_liste(daten["passt"]),
        passt_nicht=_als_string_liste(daten["passt_nicht"]),
        luecken=_als_string_liste(daten["luecken"]),
        kurzfazit=str(daten["kurzfazit"]),
    )


def _als_string_liste(wert: object) -> list[str]:
    # Claude liefert dieses Feld manchmal als einzelnen String statt als
    # JSON-Array, obwohl das Tool-Schema ein Array vorgibt. Statt die ganze
    # Bewertung zu verwerfen, wird der String als Ein-Elemente-Liste
    # uebernommen - kein Datenverlust, nur weniger granular dargestellt.
    if isinstance(wert, str):
        return [wert]
    if not isinstance(wert, list):
        raise TypeError(f"erwartete Liste oder String, bekam {type(wert)}")
    return [str(eintrag) for eintrag in wert]
