"""Seam Sprachmodell: System-Prompt, Text und JSON-Schema rein, geprüfte Daten raus."""

import json
from abc import ABC, abstractmethod
from typing import Protocol, cast

import anthropic
from anthropic.types import Message
from anthropic.types.beta import BetaMessage

from jobagent.text import encodable_data

_MAX_TOKENS = 1024
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_TOOL_NAME = "antwort_abgeben"
_TOOL_ANNOTATIONS = ("title", "description")


class LanguageModelError(Exception):
    """Das Sprachmodell hat keine brauchbare Antwort geliefert, gleich aus welchem Grund."""


class LanguageModel(Protocol):
    def ask(self, system: str, text: str, schema: dict) -> dict:
        """Fragt das Sprachmodell und liefert seine Antwort als Daten nach `schema`.

        Wirft nur `LanguageModelError`, nie einen Fehler des SDK dahinter. Jede Umsetzung
        gibt ihre Antwort durch `with_required_keys`: Pflichtschlüssel sind da, und Texte
        enthalten keine einzelnen Surrogate.
        """
        ...


class AnthropicLanguageModel[Response](ABC):
    """Gemeinsamer Teil der Sprachmodelle von Anthropic: Client, Fehler und Prüfung am Seam.

    Wie gefragt und die Antwort gelesen wird, legen die beiden Adapter fest:
    `AnthropicToolLanguageModel` für die Bewertung, `AnthropicJsonLanguageModel` für den
    Profil-Vorschlag.
    """

    def __init__(
        self,
        model: str,
        *,
        max_tokens: int = _MAX_TOKENS,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = client

    def ask(self, system: str, text: str, schema: dict) -> dict:
        try:
            if self._client is None:
                self._client = anthropic.Anthropic()  # einmal je Instanz, nicht je Frage
            response = self._send(self._client, system, text, schema)
        except (anthropic.AnthropicError, TypeError) as error:
            # TypeError: So meldet das SDK einen fehlenden ANTHROPIC_API_KEY, schon beim
            # Aufbau der Anfrage und nicht als AnthropicError.
            raise LanguageModelError(f"Anthropic-API-Anfrage fehlgeschlagen: {error}") from error

        # Das Auswerten steht außerhalb des try, damit ein Programmfehler dabei nicht
        # wie ein Fehler der API aussieht.
        return with_required_keys(schema, self._answer_from(response))

    @abstractmethod
    def _send(self, client: anthropic.Anthropic, system: str, text: str, schema: dict) -> Response:
        """Schickt die Anfrage; Fehler des SDK übersetzt `ask`."""

    @abstractmethod
    def _answer_from(self, response: Response) -> dict:
        """Liest die Daten aus der Antwort; wirft `LanguageModelError`, wenn das nicht geht."""


class AnthropicToolLanguageModel(AnthropicLanguageModel[Message]):
    """Sprachmodell von Anthropic, das über ein erzwungenes Werkzeug mit dem Schema antwortet.

    Ein erzwungenes Werkzeug lässt kein Nachdenken des Modells zu; für die Bewertung mit
    Haiku braucht es das nicht.
    """

    def _send(self, client: anthropic.Anthropic, system: str, text: str, schema: dict) -> Message:
        tool = _tool_for(schema)
        return client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=_messages(text),
        )

    def _answer_from(self, response: Message) -> dict:
        return _tool_input_from(response)


class AnthropicJsonLanguageModel(AnthropicLanguageModel[BetaMessage]):
    """Sprachmodell von Anthropic, das als JSON-Text nach dem Schema antwortet.

    Vorher darf es nachdenken, wie Sonnet es von sich aus tut. Die Anfrage läuft über die
    Beta-Schnittstelle mit serverseitigem Fallback auf ein anderes Modell.
    """

    def _send(
        self, client: anthropic.Anthropic, system: str, text: str, schema: dict
    ) -> BetaMessage:
        return client.beta.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            betas=[_FALLBACK_BETA],
            fallbacks="default",
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=_messages(text),
        )

    def _answer_from(self, response: BetaMessage) -> dict:
        return _json_object_from(response)


def _messages(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


def _tool_input_from(response: Message) -> dict:
    if response.stop_reason != "tool_use":
        # z.B. max_tokens: Der Werkzeug-Input ist dann womöglich abgeschnitten, auch wenn
        # alle Pflichtschlüssel schon drinstehen.
        raise LanguageModelError(
            f"Keine vollständige Werkzeug-Antwort (stop_reason={response.stop_reason!r})"
        )
    data = next((block.input for block in response.content if block.type == "tool_use"), None)
    if data is None:
        raise LanguageModelError("Antwort enthält keinen Werkzeug-Aufruf")
    return data


def _json_object_from(response: BetaMessage) -> dict:
    if response.stop_reason != "end_turn":
        # z.B. max_tokens oder refusal: Der Text ist dann abgeschnitten oder fehlt.
        raise LanguageModelError(f"Antwort unvollständig (stop_reason={response.stop_reason!r})")
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise LanguageModelError("Antwort enthält keinen Text")
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as error:  # RecursionError: sehr tief verschachtelt
        raise LanguageModelError(f"Antwort ist kein JSON: {text!r}") from error
    if not isinstance(data, dict):
        raise LanguageModelError(f"Antwort ist kein JSON-Objekt: {text!r}")
    return data


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
        raise LanguageModelError("Antwort ist zu tief verschachtelt") from error


def _checked(schema: dict, data: dict) -> dict:
    # Auch repr und Bereinigung gehen rekursiv durch die Antwort, daher alles im try oben.
    if not isinstance(data, dict):
        raise LanguageModelError(f"Antwort ist kein Objekt: {data!r}")
    missing = [key for key in schema.get("required", []) if key not in data]
    if missing:
        raise LanguageModelError(f"Antwort ohne Pflichtschlüssel {missing}: {data!r}")
    return cast(dict, encodable_data(data))
