"""Seam Sprachmodell: System-Prompt, Text und JSON-Schema rein, geprüfte Daten raus."""

from typing import Protocol

import anthropic

_MAX_TOKENS = 1024
_TOOL_NAME = "antwort_abgeben"


class LanguageModelError(Exception):
    """Das Sprachmodell hat keine brauchbare Antwort geliefert, gleich aus welchem Grund."""


class LanguageModel(Protocol):
    def ask(self, system: str, text: str, schema: dict) -> dict:
        """Fragt das Sprachmodell und liefert seine Antwort als Daten nach `schema`.

        Wirft nur `LanguageModelError`, nie einen Fehler des Anbieters.
        """
        ...


class AnthropicLanguageModel:
    """Sprachmodell von Anthropic; die Antwort erzwingt ein Werkzeug mit dem Schema."""

    def __init__(self, model: str, *, client: anthropic.Anthropic | None = None) -> None:
        self._model = model
        self._client = client

    def ask(self, system: str, text: str, schema: dict) -> dict:
        try:
            client = self._client or anthropic.Anthropic()
            response = client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=system,
                tools=[{"name": _TOOL_NAME, "input_schema": schema}],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": text}],
            )
        except (anthropic.AnthropicError, TypeError) as error:
            # TypeError: So meldet das SDK z.B. einen fehlenden ANTHROPIC_API_KEY, schon
            # beim Aufbau der Anfrage und nicht als AnthropicError.
            raise LanguageModelError(f"Anthropic-API-Anfrage fehlgeschlagen: {error}") from error

        data = next((block.input for block in response.content if block.type == "tool_use"), None)
        if data is None:
            raise LanguageModelError(
                f"Keine Werkzeug-Antwort (stop_reason={response.stop_reason!r})"
            )
        return _with_required_keys(schema, data)


def _with_required_keys(schema: dict, data: dict) -> dict:
    # Die Prüfung gegen das Schema bleibt bewusst grob: Feinere Regeln (Wertebereiche,
    # Typen einzelner Felder) prüft, wer fragt, weil nur er weiß, was er davon
    # nachsichtig behandelt (die Bewertung nimmt z.B. einen String statt einer Liste).
    missing = [key for key in schema.get("required", []) if key not in data]
    if missing:
        raise LanguageModelError(f"Antwort ohne Pflichtschlüssel {missing}: {data!r}")
    return data
