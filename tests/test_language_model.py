"""Tests für den Anthropic-Adapter am Seam Sprachmodell, mit nachgebautem SDK-Client."""

from typing import cast

import anthropic
import httpx2
import pytest
from anthropic.types import ContentBlock, Message, StopReason, TextBlock, ToolUseBlock, Usage
from anthropic.types.beta import (
    BetaContentBlock,
    BetaMessage,
    BetaStopReason,
    BetaTextBlock,
    BetaThinkingBlock,
    BetaUsage,
)

from jobagent.language_model import (
    AnthropicJsonLanguageModel,
    AnthropicToolLanguageModel,
    LanguageModelError,
    LanguageModelFailure,
    with_required_keys,
)

_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer"}, "kurzfazit": {"type": "string"}},
    "required": ["score", "kurzfazit"],
}


def _message(*content: ContentBlock, stop_reason: StopReason = "tool_use") -> Message:
    return Message(
        id="msg_1",
        content=list(content),
        model="claude-haiku-4-5-20251001",
        role="assistant",
        stop_reason=stop_reason,
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _tool_answer(data: dict) -> Message:
    return _message(ToolUseBlock(id="toolu_1", input=data, name="antwort_abgeben", type="tool_use"))


class _FakeMessages:
    def __init__(self, result: object) -> None:
        self._result = result
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def sent(self) -> dict:
        """Die Argumente der letzten Anfrage; es muss eine gegeben haben."""
        assert self.last_kwargs is not None
        return self.last_kwargs


class _FakeBeta:
    def __init__(self, result: object) -> None:
        self.messages = _FakeMessages(result)


class _FakeClient:
    def __init__(self, result: object) -> None:
        self.messages = _FakeMessages(result)
        self.beta = _FakeBeta(result)

    def as_anthropic(self) -> anthropic.Anthropic:
        # Nachgebaut sind nur messages und beta.messages, mehr nutzen die Adapter nicht.
        return cast(anthropic.Anthropic, self)


def _ask(result: object) -> dict:
    model = AnthropicToolLanguageModel(
        "claude-haiku-4-5-20251001", client=_FakeClient(result).as_anthropic()
    )
    return model.ask("System", "Text", _SCHEMA)


def test_ask_returns_data_of_forced_tool() -> None:
    assert _ask(_tool_answer({"score": 4, "kurzfazit": "Passt."})) == {
        "score": 4,
        "kurzfazit": "Passt.",
    }


def test_ask_sends_model_system_text_and_schema_as_forced_tool() -> None:
    client = _FakeClient(_tool_answer({"score": 4, "kurzfazit": "Passt."}))

    AnthropicToolLanguageModel("modell-x", client=client.as_anthropic()).ask(
        "Sei knapp.", "Anzeige", _SCHEMA
    )

    kwargs = client.messages.sent()
    assert kwargs["model"] == "modell-x"
    assert kwargs["system"] == "Sei knapp."
    assert kwargs["messages"] == [{"role": "user", "content": "Anzeige"}]
    assert kwargs["tools"][0]["input_schema"] == _SCHEMA
    assert kwargs["tool_choice"] == {"type": "tool", "name": kwargs["tools"][0]["name"]}


def test_schema_title_and_description_name_and_describe_the_tool() -> None:
    client = _FakeClient(_tool_answer({"score": 4, "kurzfazit": "Passt."}))
    schema = {"title": "bewertung_abgeben", "description": "Gibt die Bewertung zurück.", **_SCHEMA}

    AnthropicToolLanguageModel("modell-x", client=client.as_anthropic()).ask(
        "System", "Text", schema
    )

    kwargs = client.messages.sent()
    assert kwargs["tools"] == [
        {
            "name": "bewertung_abgeben",
            "description": "Gibt die Bewertung zurück.",
            "input_schema": _SCHEMA,
        }
    ]
    assert kwargs["tool_choice"] == {"type": "tool", "name": "bewertung_abgeben"}


_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APIConnectionError(request=_REQUEST),
        anthropic.APITimeoutError(request=_REQUEST),
        anthropic.InternalServerError(
            "Überlastet", response=httpx2.Response(529, request=_REQUEST), body=None
        ),
    ],
)
def test_api_error_becomes_language_model_error_unreachable(error: Exception) -> None:
    with pytest.raises(LanguageModelError) as caught:
        _ask(error)

    assert caught.value.failure is LanguageModelFailure.UNREACHABLE


def test_missing_api_key_becomes_language_model_error_missing_api_key() -> None:
    # So meldet das SDK 2.x einen fehlenden ANTHROPIC_API_KEY: als rohen TypeError beim
    # Aufbau der Anfrage, nicht als AnthropicError (geprüft mit dem echten Client).
    with pytest.raises(LanguageModelError) as caught:
        _ask(TypeError("Could not resolve authentication method."))

    assert caught.value.failure is LanguageModelFailure.MISSING_API_KEY


@pytest.mark.parametrize(
    "answer",
    [
        _message(TextBlock(text="Freitext statt Werkzeug", type="text"), stop_reason="end_turn"),
        _tool_answer({"score": 4}),
        _message(
            ToolUseBlock(id="toolu_1", input={"score": 4}, name="x", type="tool_use"),
            stop_reason="max_tokens",
        ),
    ],
)
def test_unusable_tool_answer_is_marked_as_unusable(answer: Message) -> None:
    with pytest.raises(LanguageModelError) as caught:
        _ask(answer)

    assert caught.value.failure is LanguageModelFailure.UNUSABLE_ANSWER


def test_client_is_created_once_for_all_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    clients: list[_FakeClient] = []

    def create_client() -> _FakeClient:
        clients.append(_FakeClient(_tool_answer({"score": 4, "kurzfazit": "Passt."})))
        return clients[-1]

    monkeypatch.setattr(anthropic, "Anthropic", create_client)
    model = AnthropicToolLanguageModel("claude-haiku-4-5-20251001")

    model.ask("System", "Erste Anzeige", _SCHEMA)
    model.ask("System", "Zweite Anzeige", _SCHEMA)

    assert len(clients) == 1


def test_answer_without_tool_becomes_language_model_error() -> None:
    answer = _message(
        TextBlock(text="Freitext statt Werkzeug", type="text"), stop_reason="end_turn"
    )

    with pytest.raises(LanguageModelError):
        _ask(answer)


def test_answer_without_required_key_becomes_language_model_error() -> None:
    with pytest.raises(LanguageModelError):
        _ask(_tool_answer({"score": 4}))


def test_cut_off_tool_answer_becomes_language_model_error() -> None:
    # Bei max_tokens kann der Werkzeug-Input abgeschnitten sein, auch wenn alle
    # Pflichtschlüssel schon drinstehen.
    answer = _message(
        ToolUseBlock(
            id="toolu_1",
            input={"score": 4, "kurzfazit": "Pas"},
            name="antwort_abgeben",
            type="tool_use",
        ),
        stop_reason="max_tokens",
    )

    with pytest.raises(LanguageModelError):
        _ask(answer)


@pytest.mark.parametrize("tool_input", [["score", "kurzfazit"], "score kurzfazit", 5])
def test_tool_answer_that_is_no_object_becomes_language_model_error(tool_input: object) -> None:
    answer = _message(
        ToolUseBlock.model_construct(
            id="toolu_1", input=tool_input, name="antwort_abgeben", type="tool_use"
        )
    )

    with pytest.raises(LanguageModelError):
        _ask(answer)


def test_max_tokens_reaches_the_tool_request() -> None:
    client = _FakeClient(_tool_answer({"score": 4, "kurzfazit": "Passt."}))

    AnthropicToolLanguageModel("modell-x", max_tokens=2048, client=client.as_anthropic()).ask(
        "S", "T", _SCHEMA
    )

    assert client.messages.sent()["max_tokens"] == 2048


def _beta_message(
    *content: BetaContentBlock, stop_reason: BetaStopReason = "end_turn"
) -> BetaMessage:
    return BetaMessage(
        id="msg_2",
        content=list(content),
        model="claude-sonnet-5-5",
        role="assistant",
        stop_reason=stop_reason,
        stop_sequence=None,
        type="message",
        usage=BetaUsage(input_tokens=10, output_tokens=5),
    )


def _thought_and_text(text: str, stop_reason: BetaStopReason = "end_turn") -> BetaMessage:
    return _beta_message(
        BetaThinkingBlock(signature="sig", thinking="Erst nachdenken.", type="thinking"),
        BetaTextBlock(text=text, type="text"),
        stop_reason=stop_reason,
    )


def _ask_json_model(result: object) -> dict:
    model = AnthropicJsonLanguageModel(
        "claude-sonnet-5-5", client=_FakeClient(result).as_anthropic()
    )
    return model.ask("System", "Text", _SCHEMA)


def test_json_answer_replaces_lone_surrogates() -> None:
    # json.loads macht aus "\ud83d" ein einzelnes Surrogat, das UTF-8 nicht schreiben kann.
    answer = _thought_and_text('{"score": 4, "kurzfazit": "Passt \\ud83d", "x": [["a \\udc00"]]}')

    assert _ask_json_model(answer) == {"score": 4, "kurzfazit": "Passt ?", "x": [["a ?"]]}


def _deeply_nested(depth: int = 100_000) -> list:
    nested: list = []
    for _ in range(depth):
        nested = [nested]
    return nested


@pytest.mark.parametrize(
    "answer",
    [
        {"score": 4, "kurzfazit": "x", "tief": _deeply_nested()},  # Bereinigung der Texte
        {"score": 4, "tief": _deeply_nested()},  # repr in der Meldung zum fehlenden Schlüssel
    ],
)
def test_deeply_nested_answer_becomes_language_model_error(answer: dict) -> None:
    with pytest.raises(LanguageModelError):
        with_required_keys(_SCHEMA, answer)


def test_json_answer_after_thinking_returns_its_data() -> None:
    assert _ask_json_model(_thought_and_text('{"score": 4, "kurzfazit": "Passt."}')) == {
        "score": 4,
        "kurzfazit": "Passt.",
    }


def test_json_answer_is_asked_with_fallback_instead_of_tool() -> None:
    client = _FakeClient(_thought_and_text('{"score": 4, "kurzfazit": "Passt."}'))
    model = AnthropicJsonLanguageModel("modell-y", max_tokens=16000, client=client.as_anthropic())

    model.ask("Denk nach.", "Rückmeldungen", _SCHEMA)

    assert client.messages.last_kwargs is None
    assert client.beta.messages.last_kwargs == {
        "model": "modell-y",
        "max_tokens": 16000,
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
        "system": "Denk nach.",
        "output_config": {"format": {"type": "json_schema", "schema": _SCHEMA}},
        "messages": [{"role": "user", "content": "Rückmeldungen"}],
    }


@pytest.mark.parametrize(
    "answer",
    [
        _thought_and_text("kein json"),
        _thought_and_text('["keine", "Daten"]'),
        _thought_and_text('{"score": 4}'),
        _thought_and_text("[" * 100_000 + "]" * 100_000),
        _thought_and_text('{"score": 4, "kurzfazit": "x"}', stop_reason="max_tokens"),
        _thought_and_text('{"score": 4, "kurzfazit": "x"}', stop_reason="refusal"),
        _beta_message(),
    ],
)
def test_unusable_json_answer_becomes_language_model_error(answer: object) -> None:
    with pytest.raises(LanguageModelError) as caught:
        _ask_json_model(answer)

    assert caught.value.failure is LanguageModelFailure.UNUSABLE_ANSWER


@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (
            TypeError("Could not resolve authentication method."),
            LanguageModelFailure.MISSING_API_KEY,
        ),
        (anthropic.APIConnectionError(request=_REQUEST), LanguageModelFailure.UNREACHABLE),
    ],
)
def test_json_model_tells_failures_of_the_request_apart(
    error: Exception, failure: LanguageModelFailure
) -> None:
    with pytest.raises(LanguageModelError) as caught:
        _ask_json_model(error)

    assert caught.value.failure is failure
