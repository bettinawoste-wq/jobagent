"""Bewertung einer Anzeige gegen profile.md via Anthropic API (Modell Haiku)."""

import logging
from dataclasses import dataclass

import anthropic

from jobagent.fetch import Anzeige

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
    "Wiederholung von passt/passt_nicht/luecken."
)


@dataclass(frozen=True, slots=True)
class Bewertung:
    score: int
    passt: list[str]
    passt_nicht: list[str]
    luecken: list[str]
    kurzfazit: str


def score_anzeige(
    anzeige: Anzeige,
    profil: str,
    *,
    client: anthropic.Anthropic | None = None,
) -> Bewertung | None:
    """Bewertet eine Anzeige gegen das Suchprofil mittels Claude Haiku.

    Gibt None zurueck und loggt, wenn die Anthropic-API nicht erreichbar ist
    oder eine ungueltige Antwort liefert, statt den Lauf abzubrechen.
    """
    aktiver_client = client or anthropic.Anthropic()

    nutzertext = f"Suchprofil:\n{profil}\n\nStellenanzeige:\n{_anzeige_zu_text(anzeige)}"
    try:
        antwort = aktiver_client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": nutzertext}],
        )
    except anthropic.AnthropicError:
        logger.exception("Anthropic-API-Anfrage fehlgeschlagen (anzeige=%r)", anzeige.id)
        return None

    return _zu_bewertung(antwort, anzeige.id)


def _anzeige_zu_text(anzeige: Anzeige) -> str:
    zeilen = [
        f"Titel: {anzeige.titel}",
        f"Firma: {anzeige.firma or 'unbekannt'}",
        f"Ort: {anzeige.ort or 'unbekannt'}",
    ]
    if anzeige.beschreibung:
        zeilen.append(f"Beschreibung: {anzeige.beschreibung}")
    return "\n".join(zeilen)


def _zu_bewertung(antwort: anthropic.types.Message, anzeige_id: str) -> Bewertung | None:
    tool_use = next((block for block in antwort.content if block.type == "tool_use"), None)
    if tool_use is None:
        logger.error("Keine Tool-Antwort von Claude erhalten (anzeige=%r)", anzeige_id)
        return None

    try:
        return _validiere(tool_use.input)
    except (KeyError, TypeError, ValueError):
        logger.exception(
            "Ungueltige Bewertungsantwort (anzeige=%r): %r", anzeige_id, tool_use.input
        )
        return None


def _validiere(daten: dict) -> Bewertung:
    score = int(daten["score"])
    if not 1 <= score <= 5:
        raise ValueError(f"score ausserhalb 1-5: {score}")

    return Bewertung(
        score=score,
        passt=_als_string_liste(daten["passt"]),
        passt_nicht=_als_string_liste(daten["passt_nicht"]),
        luecken=_als_string_liste(daten["luecken"]),
        kurzfazit=str(daten["kurzfazit"]),
    )


def _als_string_liste(wert: object) -> list[str]:
    if not isinstance(wert, list):
        raise TypeError(f"erwartete Liste, bekam {type(wert)}")
    return [str(eintrag) for eintrag in wert]
