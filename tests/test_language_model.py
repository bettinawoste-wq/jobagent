"""Tests für den Anthropic-Adapter am Seam Sprachmodell, mit nachgebautem SDK-Client."""

import anthropic
import httpx2
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

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


class _FakeClient:
    def __init__(self, result: object) -> None:
        self.messages = _FakeMessages(result)


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


def test_api_error_becomes_language_model_error() -> None:
    error = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )

    with pytest.raises(LanguageModelError):
        _ask(error)


def test_missing_api_key_becomes_language_model_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Echter SDK-Client: Ohne Schlüssel scheitert er schon beim Aufbau der Anfrage,
    # vor jedem Netzzugriff, und zwar mit einem rohen TypeError.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    with pytest.raises(LanguageModelError):
        AnthropicLanguageModel("claude-haiku-4-5-20251001").ask("System", "Text", _SCHEMA)


def test_answer_without_tool_becomes_language_model_error() -> None:
    answer = _message(
        TextBlock(text="Freitext statt Werkzeug", type="text"), stop_reason="end_turn"
    )

    with pytest.raises(LanguageModelError):
        _ask(answer)


def test_answer_without_required_key_becomes_language_model_error() -> None:
    with pytest.raises(LanguageModelError):
        _ask(_tool_answer({"score": 4}))
