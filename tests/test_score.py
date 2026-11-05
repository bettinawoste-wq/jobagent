"""Tests fuer score.py mit gemocktem Anthropic-Client."""

import json
from pathlib import Path

import anthropic
import httpx2
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from jobagent.fetch import Anzeige
from jobagent.score import score_anzeige

SCORE_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "score_response.json").read_text(encoding="utf-8")
)

_PROFIL = "# Suchprofil\nPython, SQL, München, Hybrid bevorzugt."


def _anzeige() -> Anzeige:
    return Anzeige(
        id="10001-1003353506-S",
        titel="Softwareentwickler/in (m/w/d)",
        firma="Beispiel GmbH",
        ort="München",
        link="https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003353506-S",
        beschreibung="Python-Backend, CI/CD, etwas Kubernetes von Vorteil.",
    )


def _nachricht_mit_tool_input(daten: dict) -> Message:
    block = ToolUseBlock(id="toolu_1", input=daten, name="bewertung_abgeben", type="tool_use")
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
    def __init__(self, ergebnis):
        self._ergebnis = ergebnis
        self.letzte_kwargs: dict | None = None

    def create(self, **kwargs):
        self.letzte_kwargs = kwargs
        if isinstance(self._ergebnis, Exception):
            raise self._ergebnis
        return self._ergebnis


class _FakeClient:
    def __init__(self, ergebnis):
        self.messages = _FakeMessages(ergebnis)


def test_score_anzeige_erfolgreiche_bewertung() -> None:
    client = _FakeClient(_nachricht_mit_tool_input(SCORE_FIXTURE))

    bewertung = score_anzeige(_anzeige(), _PROFIL, client=client)

    assert bewertung is not None
    assert bewertung.score == 4
    assert bewertung.passt == SCORE_FIXTURE["passt"]
    assert bewertung.passt_nicht == []
    assert bewertung.luecken == SCORE_FIXTURE["luecken"]
    assert bewertung.kurzfazit == SCORE_FIXTURE["kurzfazit"]


def test_score_anzeige_sendet_profil_anzeige_und_tool_schema() -> None:
    client = _FakeClient(_nachricht_mit_tool_input(SCORE_FIXTURE))

    score_anzeige(_anzeige(), _PROFIL, client=client)

    kwargs = client.messages.letzte_kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "bewertung_abgeben"}
    assert kwargs["tools"][0]["name"] == "bewertung_abgeben"
    inhalt = kwargs["messages"][0]["content"]
    assert _PROFIL in inhalt
    assert "Softwareentwickler/in (m/w/d)" in inhalt
    assert "Kubernetes" in inhalt


def test_score_anzeige_gibt_none_bei_api_fehler(caplog: pytest.LogCaptureFixture) -> None:
    fehler = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    client = _FakeClient(fehler)

    with caplog.at_level("ERROR"):
        bewertung = score_anzeige(_anzeige(), _PROFIL, client=client)

    assert bewertung is None
    assert "fehlgeschlagen" in caplog.text


def test_score_anzeige_gibt_none_ohne_tool_use(caplog: pytest.LogCaptureFixture) -> None:
    nachricht = Message(
        id="msg_2",
        content=[TextBlock(text="Freitext statt Tool-Aufruf", type="text")],
        model="claude-haiku-4-5-20251001",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=10, output_tokens=5),
    )
    client = _FakeClient(nachricht)

    with caplog.at_level("ERROR"):
        bewertung = score_anzeige(_anzeige(), _PROFIL, client=client)

    assert bewertung is None
    assert "Keine Tool-Antwort" in caplog.text


@pytest.mark.parametrize(
    "ungueltige_daten",
    [
        {**SCORE_FIXTURE, "score": 7},
        {**SCORE_FIXTURE, "passt": "kein-liste"},
        {k: v for k, v in SCORE_FIXTURE.items() if k != "kurzfazit"},
    ],
)
def test_score_anzeige_gibt_none_bei_ungueltiger_antwort(
    ungueltige_daten: dict, caplog: pytest.LogCaptureFixture
) -> None:
    client = _FakeClient(_nachricht_mit_tool_input(ungueltige_daten))

    with caplog.at_level("ERROR"):
        bewertung = score_anzeige(_anzeige(), _PROFIL, client=client)

    assert bewertung is None
    assert "Ungueltige Bewertungsantwort" in caplog.text
