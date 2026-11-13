"""Tests für den Anthropic-Adapter am Seam Sprachmodell, mit nachgebautem SDK-Client."""

import anthropic
import httpx2
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaThinkingBlock, BetaUsage

from jobagent.language_model import AnthropicLanguageModel, LanguageModelError

_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer"}, "kurzfazit": {"type": "string"}},
    "required": ["score", "kurzfazit"],
}


def _message(*content: object, stop_reason: str = "tool_use") -> Message:
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


class _FakeBeta:
    def __init__(self, result: object) -> None:
        self.messages = _FakeMessages(result)


class _FakeClient:
    def __init__(self, result: object) -> None:
        self.messages = _FakeMessages(result)
        self.beta = _FakeBeta(result)


def _ask(result: object) -> dict:
    model = AnthropicLanguageModel("claude-haiku-4-5-20251001", client=_FakeClient(result))
    return model.ask("System", "Text", _SCHEMA)


def test_ask_returns_data_of_forced_tool() -> None:
    assert _ask(_tool_answer({"score": 4, "kurzfazit": "Passt."})) == {
        "score": 4,
        "kurzfazit": "Passt.",
    }


def test_ask_sends_model_system_text_and_schema_as_forced_tool() -> None:
    client = _FakeClient(_tool_answer({"score": 4, "kurzfazit": "Passt."}))

    AnthropicLanguageModel("modell-x", client=client).ask("Sei knapp.", "Anzeige", _SCHEMA)

    kwargs = client.messages.last_kwargs
    assert kwargs["model"] == "modell-x"
    assert kwargs["system"] == "Sei knapp."
    assert kwargs["messages"] == [{"role": "user", "content": "Anzeige"}]
    assert kwargs["tools"][0]["input_schema"] == _SCHEMA
    assert kwargs["tool_choice"] == {"type": "tool", "name": kwargs["tools"][0]["name"]}


def test_schema_title_and_description_name_and_describe_the_tool() -> None:
    client = _FakeClient(_tool_answer({"score": 4, "kurzfazit": "Passt."}))
    schema = {"title": "bewertung_abgeben", "description": "Gibt die Bewertung zurück.", **_SCHEMA}

    AnthropicLanguageModel("modell-x", client=client).ask("System", "Text", schema)

    kwargs = client.messages.last_kwargs
    assert kwargs["tools"] == [
        {
            "name": "bewertung_abgeben",
            "description": "Gibt die Bewertung zurück.",
            "input_schema": _SCHEMA,
        }
    ]
    assert kwargs["tool_choice"] == {"type": "tool", "name": "bewertung_abgeben"}


def test_api_error_becomes_language_model_error() -> None:
    error = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )

    with pytest.raises(LanguageModelError):
        _ask(error)


def test_missing_api_key_becomes_language_model_error() -> None:
    # So meldet das SDK 2.x einen fehlenden ANTHROPIC_API_KEY: als rohen TypeError beim
    # Aufbau der Anfrage, nicht als AnthropicError (geprüft mit dem echten Client).
    with pytest.raises(LanguageModelError):
        _ask(TypeError("Could not resolve authentication method."))


def test_client_is_created_once_for_all_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    clients: list[_FakeClient] = []

    def create_client() -> _FakeClient:
        clients.append(_FakeClient(_tool_answer({"score": 4, "kurzfazit": "Passt."})))
        return clients[-1]

    monkeypatch.setattr(anthropic, "Anthropic", create_client)
    model = AnthropicLanguageModel("claude-haiku-4-5-20251001")

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

    AnthropicLanguageModel("modell-x", max_tokens=2048, client=client).ask("S", "T", _SCHEMA)

    assert client.messages.last_kwargs["max_tokens"] == 2048


def _beta_message(*content: object, stop_reason: str = "end_turn") -> BetaMessage:
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


def _thought_and_text(text: str, stop_reason: str = "end_turn") -> BetaMessage:
    return _beta_message(
        BetaThinkingBlock(signature="sig", thinking="Erst nachdenken.", type="thinking"),
        BetaTextBlock(text=text, type="text"),
        stop_reason=stop_reason,
    )


def _ask_json_model(result: object) -> dict:
    model = AnthropicLanguageModel(
        "claude-sonnet-5-5", json_answer=True, client=_FakeClient(result)
    )
    return model.ask("System", "Text", _SCHEMA)


def test_json_answer_after_thinking_returns_its_data() -> None:
    assert _ask_json_model(_thought_and_text('{"score": 4, "kurzfazit": "Passt."}')) == {
        "score": 4,
        "kurzfazit": "Passt.",
    }


def test_json_answer_is_asked_with_fallback_instead_of_tool() -> None:
    client = _FakeClient(_thought_and_text('{"score": 4, "kurzfazit": "Passt."}'))
    model = AnthropicLanguageModel("modell-y", max_tokens=16000, json_answer=True, client=client)

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
        TypeError("Could not resolve authentication method."),
        anthropic.APIConnectionError(
            request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
    ],
)
def test_unusable_json_answer_becomes_language_model_error(answer: object) -> None:
    with pytest.raises(LanguageModelError):
        _ask_json_model(answer)
