"""Bewertung einer Anzeige gegen profile.md über den Seam Sprachmodell."""

import logging
from dataclasses import dataclass

from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModel, LanguageModelError

logger = logging.getLogger(__name__)

_SCHEMA = {
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
}

_SYSTEM_PROMPT = (
    "Du bewertest Stellenanzeigen gegen das Suchprofil einer Bewerberin. "
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


# Deutsche Schluessel einer Bewertung je Feld von Assessment: So sehen sie
# die Sprachmodelle (Antwort der Bewertung, Payload des Profil-Vorschlags) und die
# DB-Spalte bewertung.
ASSESSMENT_KEYS = {
    "fits": "passt",
    "misfits": "passt_nicht",
    "gaps": "luecken",
    "summary": "kurzfazit",
}


@dataclass(frozen=True, slots=True)
class Assessment:
    score: int
    fits: list[str]
    misfits: list[str]
    gaps: list[str]
    summary: str

    def as_model_data(self) -> dict[str, object]:
        """Die Bewertung ohne Score unter den deutschen Schluesseln."""
        return {key: getattr(self, field) for field, key in ASSESSMENT_KEYS.items()}

    @classmethod
    def from_model_data(cls, score: int, data: dict) -> "Assessment":
        """Gegenstueck zu as_model_data; fehlende Schluessel werfen KeyError."""
        return cls(score=score, **{field: data[key] for field, key in ASSESSMENT_KEYS.items()})


def score_job_ad(
    job_ad: JobAd,
    profile: str,
    language_model: LanguageModel,
) -> Assessment | None:
    """Bewertet eine Anzeige gegen das Suchprofil.

    Gibt None zurueck und loggt, wenn das Sprachmodell scheitert oder eine ungueltige
    Antwort liefert, statt den Lauf abzubrechen; die Anzeige bleibt dann unbewertet.
    """
    user_text = f"Suchprofil:\n{profile}\n\nStellenanzeige:\n{_job_ad_as_text(job_ad)}"
    try:
        data = language_model.ask(_SYSTEM_PROMPT, user_text, _SCHEMA)
    except LanguageModelError:
        logger.exception("Bewertung beim Sprachmodell fehlgeschlagen (anzeige=%r)", job_ad.id)
        return None

    try:
        return _validate(data)
    except (KeyError, TypeError, ValueError):
        logger.exception("Ungueltige Bewertungsantwort (anzeige=%r): %r", job_ad.id, data)
        return None


def _job_ad_as_text(job_ad: JobAd) -> str:
    lines = [
        f"Titel: {job_ad.title}",
        f"Firma: {job_ad.company or 'unbekannt'}",
        f"Ort: {job_ad.location or 'unbekannt'}",
    ]
    if job_ad.description:
        lines.append(f"Beschreibung: {job_ad.description}")
    return "\n".join(lines)


def _validate(data: dict) -> Assessment:
    score = int(data["score"])
    if not 1 <= score <= 5:
        raise ValueError(f"score ausserhalb 1-5: {score}")

    assessment = Assessment.from_model_data(score, data)
    return Assessment(
        score=score,
        fits=_as_string_list(assessment.fits),
        misfits=_as_string_list(assessment.misfits),
        gaps=_as_string_list(assessment.gaps),
        summary=str(assessment.summary),
    )


def _as_string_list(value: object) -> list[str]:
    # Claude liefert dieses Feld manchmal als einzelnen String statt als
    # JSON-Array, obwohl das Tool-Schema ein Array vorgibt. Statt die ganze
    # Bewertung zu verwerfen, wird der String als Ein-Elemente-Liste
    # uebernommen - kein Datenverlust, nur weniger granular dargestellt.
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise TypeError(f"erwartete Liste oder String, bekam {type(value)}")
    return [str(entry) for entry in value]
