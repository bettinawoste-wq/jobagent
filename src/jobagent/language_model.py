"""Seam Sprachmodell: System-Prompt, Text und JSON-Schema rein, geprüfte Daten raus.

Frei vom SDK eines Anbieters, damit Bewertung, Report, Konfiguration und Lauf es nicht
laden; die Adapter von Anthropic stehen in `jobagent.anthropic_language_model`.
"""

from enum import Enum
from typing import Protocol, cast

from jobagent.text import encodable_data


class LanguageModelFailure(Enum):
    """Woran eine Frage an das Sprachmodell gescheitert ist."""

    MISSING_API_KEY = "missing_api_key"
    UNREACHABLE = "unreachable"  # keine Verbindung, Zeitüberschreitung, überlastet, Störung
    UNUSABLE_ANSWER = "unusable_answer"
    OTHER = "other"  # z.B. Key ungültig, Modell unbekannt oder Ausgabenlimit erreicht


class LanguageModelError(Exception):
    """Das Sprachmodell hat keine brauchbare Antwort geliefert, gleich aus welchem Grund.

    Woran es lag, sagt `failure`; ohne Angabe ist es ein sonstiger Fehler.
    """

    def __init__(
        self, message: str, failure: LanguageModelFailure = LanguageModelFailure.OTHER
    ) -> None:
        super().__init__(message)
        self.failure = failure


class LanguageModel(Protocol):
    def ask(self, system: str, text: str, schema: dict) -> dict:
        """Fragt das Sprachmodell und liefert seine Antwort als Daten nach `schema`.

        Wirft nur `LanguageModelError`, nie einen Fehler des SDK dahinter; `failure` des
        `LanguageModelError` sagt, woran die Frage scheiterte. Jede Umsetzung gibt ihre
        Antwort durch `with_required_keys`: Pflichtschlüssel sind da, und Texte enthalten
        keine einzelnen Surrogate.
        """
        ...


def unusable_answer(message: str) -> LanguageModelError:
    """Fehler für eine Antwort, die sich nicht als Daten lesen lässt."""
    return LanguageModelError(message, LanguageModelFailure.UNUSABLE_ANSWER)


def with_required_keys(schema: dict, data: dict) -> dict:
    """Die Prüfung am Seam, die jedes Sprachmodell vor der Rückgabe macht.

    Sie bleibt bewusst grob: Feinere Regeln (Wertebereiche, Typen einzelner Felder)
    prüft, wer fragt, weil nur er weiß, was er davon nachsichtig behandelt (die
    Bewertung nimmt z.B. einen String statt einer Liste). Einzelne Surrogate in Texten
    der Antwort werden zu "?", damit jeder Aufrufer sie schreiben kann.
    """
    try:
        return _checked(schema, data)
    except RecursionError as error:  # sehr tief verschachtelt, wie in _json_object_from
        raise unusable_answer("Antwort ist zu tief verschachtelt") from error


def _checked(schema: dict, data: dict) -> dict:
    # Auch repr und Bereinigung gehen rekursiv durch die Antwort, daher alles im try oben.
    if not isinstance(data, dict):
        raise unusable_answer(f"Antwort ist kein Objekt: {data!r}")
    missing = [key for key in schema.get("required", []) if key not in data]
    if missing:
        raise unusable_answer(f"Antwort ohne Pflichtschlüssel {missing}: {data!r}")
    return cast(dict, encodable_data(data))
