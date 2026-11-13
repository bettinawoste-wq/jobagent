"""Seam Sprachmodell: System-Prompt, Text und JSON-Schema rein, geprüfte Daten raus."""

from typing import Protocol

import anthropic

_MAX_TOKENS = 1024
_TOOL_NAME = "antwort_abgeben"
_TOOL_ANNOTATIONS = ("title", "description")


class LanguageModelError(Exception):
    """Das Sprachmodell hat keine brauchbare Antwort geliefert, gleich aus welchem Grund."""


class LanguageModel(Protocol):
    def ask(self, system: str, text: str, schema: dict) -> dict:
        """Fragt das Sprachmodell und liefert seine Antwort als Daten nach `schema`.

        Wirft nur `LanguageModelError`, nie einen Fehler des SDK dahinter.
        """
        ...


class AnthropicLanguageModel:
    """Sprachmodell von Anthropic; die Antwort erzwingt ein Werkzeug mit dem Schema."""

    def __init__(self, model: str, *, client: anthropic.Anthropic | None = None) -> None:
        self._model = model
        self._client = client

    def ask(self, system: str, text: str, schema: dict) -> dict:
        tool = _tool_for(schema)
        try:
            client = self._client or anthropic.Anthropic()
            response = client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
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


def _tool_for(schema: dict) -> dict:
    # Titel und Beschreibung des Schemas benennen und beschreiben das Werkzeug. So bleibt
    # die Anfrage der Bewertung, deren Prompt das Werkzeug beim Namen nennt, wie vor dem
    # Seam. Die API erlaubt als Name nur ^[a-zA-Z0-9_-]{1,64}$; ein anderer Titel
    # scheitert erst bei der API und kommt als LanguageModelError zurück.
    input_schema = {key: value for key, value in schema.items() if key not in _TOOL_ANNOTATIONS}
    tool = {"name": schema.get("title", _TOOL_NAME), "input_schema": input_schema}
    if "description" in schema:
        tool["description"] = schema["description"]
    return tool


def _with_required_keys(schema: dict, data: dict) -> dict:
    # Die Prüfung gegen das Schema bleibt bewusst grob: Feinere Regeln (Wertebereiche,
    # Typen einzelner Felder) prüft, wer fragt, weil nur er weiß, was er davon
    # nachsichtig behandelt (die Bewertung nimmt z.B. einen String statt einer Liste).
    missing = [key for key in schema.get("required", []) if key not in data]
    if missing:
        raise LanguageModelError(f"Antwort ohne Pflichtschlüssel {missing}: {data!r}")
    return data
