"""Seam Sprachmodell: System-Prompt, Text und JSON-Schema rein, geprüfte Daten raus."""

import json
from abc import ABC, abstractmethod
from enum import Enum
from typing import Protocol, cast

import anthropic
from anthropic.types import Message, ToolParam
from anthropic.types.beta import BetaMessage

from jobagent.text import encodable_data

_MAX_TOKENS = 1024
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_TOOL_NAME = "antwort_abgeben"
_TOOL_ANNOTATIONS = ("title", "description")
_MISSING_API_KEY_MESSAGE = "Could not resolve authentication method"
_UNREACHABLE_ERRORS = (
    anthropic.APIConnectionError,  # samt APITimeoutError
    anthropic.RequestTimeoutError,  # 408
    anthropic.RateLimitError,  # 429
    # 5xx samt überlastet; auch die seltenen 5xx, hinter denen eine dauerhafte
    # Einstellung beim Anbieter steckt, gelten bewusst als nicht erreichbar.
    anthropic.InternalServerError,
)


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
            raise LanguageModelError(
                f"Anthropic-API-Anfrage fehlgeschlagen: {error}", _failure_of(error)
            ) from error

        # Das Auswerten steht außerhalb des try, damit ein Programmfehler dabei nicht
        # wie ein Fehler der API aussieht.
        return with_required_keys(schema, self._answer_from(response))

    @abstractmethod
    def _send(self, client: anthropic.Anthropic, system: str, text: str, schema: dict) -> Response:
        """Schickt die Anfrage; Fehler des SDK übersetzt `ask`."""

    @abstractmethod
    def _answer_from(self, response: Response) -> dict:
        """Liest die Daten aus der Antwort; wirft sonst `_unusable_answer(...)`."""


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
            messages=[{"role": "user", "content": text}],
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
            messages=[{"role": "user", "content": text}],
        )

    def _answer_from(self, response: BetaMessage) -> dict:
        return _json_object_from(response)


def _failure_of(error: Exception) -> LanguageModelFailure:
    """Woran die Anfrage scheiterte, nach dem Fehler des SDK."""
    if isinstance(error, TypeError):
        # Nur diese Meldung steht für den fehlenden Key; ein anderer TypeError ist z.B.
        # ein Programmfehler beim Aufbau der Anfrage.
        if _MISSING_API_KEY_MESSAGE in str(error):
            return LanguageModelFailure.MISSING_API_KEY
        return LanguageModelFailure.OTHER
    if isinstance(error, anthropic.EnforcedSpendLimitReachedError):
        # Ein 429 wie RateLimitError, aber bis jemand das Limit hebt, scheitert jeder Lauf.
        return LanguageModelFailure.OTHER
    if isinstance(error, _UNREACHABLE_ERRORS):
        return LanguageModelFailure.UNREACHABLE
    return LanguageModelFailure.OTHER


def _unusable_answer(message: str) -> LanguageModelError:
    return LanguageModelError(message, LanguageModelFailure.UNUSABLE_ANSWER)


def _tool_input_from(response: Message) -> dict:
    if response.stop_reason != "tool_use":
        # z.B. max_tokens: Der Werkzeug-Input ist dann womöglich abgeschnitten, auch wenn
        # alle Pflichtschlüssel schon drinstehen.
        raise _unusable_answer(
            f"Keine vollständige Werkzeug-Antwort (stop_reason={response.stop_reason!r})"
        )
    data = next((block.input for block in response.content if block.type == "tool_use"), None)
    if data is None:
        raise _unusable_answer("Antwort enthält keinen Werkzeug-Aufruf")
    return data


def _json_object_from(response: BetaMessage) -> dict:
    if response.stop_reason != "end_turn":
        # z.B. max_tokens oder refusal: Der Text ist dann abgeschnitten oder fehlt.
        raise _unusable_answer(f"Antwort unvollständig (stop_reason={response.stop_reason!r})")
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise _unusable_answer("Antwort enthält keinen Text")
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as error:  # RecursionError: sehr tief verschachtelt
        raise _unusable_answer(f"Antwort ist kein JSON: {text!r}") from error
    if not isinstance(data, dict):
        raise _unusable_answer(f"Antwort ist kein JSON-Objekt: {text!r}")
    return data


def _tool_for(schema: dict) -> ToolParam:
    # Titel und Beschreibung des Schemas benennen und beschreiben das Werkzeug. So bleibt
    # die Anfrage der Bewertung, deren Prompt das Werkzeug beim Namen nennt, wie vor dem
    # Seam. Die API erlaubt als Name nur ^[a-zA-Z0-9_-]{1,64}$; ein anderer Titel
    # scheitert erst bei der API und kommt als LanguageModelError zurück.
    input_schema = {key: value for key, value in schema.items() if key not in _TOOL_ANNOTATIONS}
    tool: ToolParam = {"name": schema.get("title", _TOOL_NAME), "input_schema": input_schema}
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
        raise _unusable_answer("Antwort ist zu tief verschachtelt") from error


def _checked(schema: dict, data: dict) -> dict:
    # Auch repr und Bereinigung gehen rekursiv durch die Antwort, daher alles im try oben.
    if not isinstance(data, dict):
        raise _unusable_answer(f"Antwort ist kein Objekt: {data!r}")
    missing = [key for key in schema.get("required", []) if key not in data]
    if missing:
        raise _unusable_answer(f"Antwort ohne Pflichtschlüssel {missing}: {data!r}")
    return cast(dict, encodable_data(data))
