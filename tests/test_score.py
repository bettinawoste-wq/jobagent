"""Tests fuer score.py mit gemocktem Anthropic-Client."""

import json
from pathlib import Path

import anthropic
import httpx2
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from jobagent.job_ad import JobAd
from jobagent.score import score_job_ad

SCORE_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "score_response.json").read_text(encoding="utf-8")
)

_PROFILE = "# Suchprofil\nPython, SQL, München, Hybrid bevorzugt."


def _job_ad() -> JobAd:
    return JobAd(
        id="10001-1003353506-S",
        title="Softwareentwickler/in (m/w/d)",
        company="Beispiel GmbH",
        location="München",
        link="https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003353506-S",
        description="Python-Backend, CI/CD, etwas Kubernetes von Vorteil.",
    )


def _message_with_tool_input(data: dict) -> Message:
    block = ToolUseBlock(id="toolu_1", input=data, name="bewertung_abgeben", type="tool_use")
    return Message(
        id="msg_1",
        content=[block],
        model="claude-haiku-4-5-20251001",
        role="assistant",
        stop_reason="tool_use",
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=10, output_tokens=5),
    )


class _FakeMessages:
    def __init__(self, result):
        self._result = result
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeClient:
    def __init__(self, result):
        self.messages = _FakeMessages(result)


def test_score_job_ad_returns_assessment() -> None:
    client = _FakeClient(_message_with_tool_input(SCORE_FIXTURE))

    assessment = score_job_ad(_job_ad(), _PROFILE, client=client)

    assert assessment is not None
    assert assessment.score == 4
    assert assessment.fits == SCORE_FIXTURE["passt"]
    assert assessment.misfits == []
    assert assessment.gaps == SCORE_FIXTURE["luecken"]
    assert assessment.summary == SCORE_FIXTURE["kurzfazit"]


def test_score_job_ad_sends_profile_job_ad_and_tool_schema() -> None:
    client = _FakeClient(_message_with_tool_input(SCORE_FIXTURE))

    score_job_ad(_job_ad(), _PROFILE, client=client)

    kwargs = client.messages.last_kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "bewertung_abgeben"}
    assert kwargs["tools"][0]["name"] == "bewertung_abgeben"
    content = kwargs["messages"][0]["content"]
    assert _PROFILE in content
    assert "Softwareentwickler/in (m/w/d)" in content
    assert "Kubernetes" in content


def test_score_job_ad_returns_none_on_api_error(caplog: pytest.LogCaptureFixture) -> None:
    error = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    client = _FakeClient(error)

    with caplog.at_level("ERROR"):
        assessment = score_job_ad(_job_ad(), _PROFILE, client=client)

    assert assessment is None
    assert "fehlgeschlagen" in caplog.text


def test_score_job_ad_returns_none_without_api_key(caplog: pytest.LogCaptureFixture) -> None:
    # Die SDK wirft hierfuer einen rohen TypeError statt eines AnthropicError
    # (Validierung erst beim Request-Aufbau, nicht bei Client.create()).
    client = _FakeClient(TypeError("Could not resolve authentication method."))

    with caplog.at_level("ERROR"):
        assessment = score_job_ad(_job_ad(), _PROFILE, client=client)

    assert assessment is None
    assert "fehlgeschlagen" in caplog.text


def test_score_job_ad_returns_none_without_tool_use(caplog: pytest.LogCaptureFixture) -> None:
    message = Message(
        id="msg_2",
        content=[TextBlock(text="Freitext statt Tool-Aufruf", type="text")],
        model="claude-haiku-4-5-20251001",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=10, output_tokens=5),
    )
    client = _FakeClient(message)

    with caplog.at_level("ERROR"):
        assessment = score_job_ad(_job_ad(), _PROFILE, client=client)

    assert assessment is None
    assert "Keine Tool-Antwort" in caplog.text


@pytest.mark.parametrize(
    "invalid_data",
    [
        {**SCORE_FIXTURE, "score": 7},
        {**SCORE_FIXTURE, "passt": 123},
        {k: v for k, v in SCORE_FIXTURE.items() if k != "kurzfazit"},
    ],
)
def test_score_job_ad_returns_none_on_invalid_response(
    invalid_data: dict, caplog: pytest.LogCaptureFixture
) -> None:
    client = _FakeClient(_message_with_tool_input(invalid_data))

    with caplog.at_level("ERROR"):
        assessment = score_job_ad(_job_ad(), _PROFILE, client=client)

    assert assessment is None
    assert "Ungueltige Bewertungsantwort" in caplog.text


def test_score_job_ad_accepts_string_instead_of_list() -> None:
    # Claude liefert passt/passt_nicht/luecken manchmal als einzelnen String
    # statt als JSON-Array, obwohl das Tool-Schema ein Array vorgibt. Das
    # darf die Anzeige nicht verwerfen, sondern wird als Ein-Elemente-Liste
    # uebernommen.
    data = {**SCORE_FIXTURE, "passt": "München-Standort, Hybrid möglich"}
    client = _FakeClient(_message_with_tool_input(data))

    assessment = score_job_ad(_job_ad(), _PROFILE, client=client)

    assert assessment is not None
    assert assessment.fits == ["München-Standort, Hybrid möglich"]
