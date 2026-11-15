"""Tests für die Bewertung (score.py) mit einem Fake am Seam Sprachmodell."""

import json
from pathlib import Path

import pytest

from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModelError
from jobagent.score import Assessment, score_job_ad
from tests.fakes import FakeLanguageModel

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


def test_score_job_ad_returns_assessment() -> None:
    assessment = score_job_ad(_job_ad(), _PROFILE, FakeLanguageModel(SCORE_FIXTURE))

    assert assessment is not None
    assert assessment.score == 4
    assert assessment.fits == SCORE_FIXTURE["passt"]
    assert assessment.misfits == []
    assert assessment.gaps == SCORE_FIXTURE["luecken"]
    assert assessment.summary == SCORE_FIXTURE["kurzfazit"]


def test_score_job_ad_asks_with_profile_job_ad_and_german_schema() -> None:
    model = FakeLanguageModel(SCORE_FIXTURE)

    score_job_ad(_job_ad(), _PROFILE, model)

    [request] = model.requests
    assert _PROFILE in request.text
    assert "Softwareentwickler/in (m/w/d)" in request.text
    assert "Kubernetes" in request.text
    assert "Score-Skala" in request.system
    # So nannte die Bewertung das erzwungene Werkzeug schon immer (unveränderte Anfrage).
    assert request.schema["title"] == "bewertung_abgeben"
    assert "Werkzeug bewertung_abgeben" in request.system
    assert request.schema["required"] == ["score", "passt", "passt_nicht", "luecken", "kurzfazit"]


def test_score_job_ad_returns_none_on_language_model_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = FakeLanguageModel(LanguageModelError("Netz weg"))

    with caplog.at_level("ERROR"):
        assessment = score_job_ad(_job_ad(), _PROFILE, model)

    assert assessment is None
    assert "fehlgeschlagen" in caplog.text
    assert "10001-1003353506-S" in caplog.text


@pytest.mark.parametrize(
    "invalid_data",
    [
        {**SCORE_FIXTURE, "score": 7},
        {**SCORE_FIXTURE, "passt": 123},
    ],
)
def test_score_job_ad_returns_none_on_invalid_response(
    invalid_data: dict, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("ERROR"):
        assessment = score_job_ad(_job_ad(), _PROFILE, FakeLanguageModel(invalid_data))

    assert assessment is None
    assert "Ungültige Bewertungsantwort" in caplog.text


def test_score_job_ad_returns_none_without_required_key(caplog: pytest.LogCaptureFixture) -> None:
    # Fehlt ein Pflichtschlüssel des Schemas, scheitert schon das Sprachmodell am Seam.
    data = {k: v for k, v in SCORE_FIXTURE.items() if k != "kurzfazit"}

    with caplog.at_level("ERROR"):
        assessment = score_job_ad(_job_ad(), _PROFILE, FakeLanguageModel(data))

    assert assessment is None
    assert "fehlgeschlagen" in caplog.text


def test_score_job_ad_accepts_string_instead_of_list() -> None:
    # Claude liefert passt/passt_nicht/luecken manchmal als einzelnen String
    # statt als JSON-Array, obwohl das Schema ein Array vorgibt. Das
    # darf die Anzeige nicht verwerfen, sondern wird als Ein-Elemente-Liste
    # uebernommen.
    data = {**SCORE_FIXTURE, "passt": "München-Standort, Hybrid möglich"}

    assessment = score_job_ad(_job_ad(), _PROFILE, FakeLanguageModel(data))

    assert assessment is not None
    assert assessment.fits == ["München-Standort, Hybrid möglich"]


def test_assessment_model_data_uses_german_keys_and_round_trips() -> None:
    assessment = Assessment(score=4, fits=["a"], misfits=["b"], gaps=["c"], summary="d")

    data = assessment.as_model_data()

    assert list(data) == ["passt", "passt_nicht", "luecken", "kurzfazit"]
    assert Assessment.from_model_data(4, data) == assessment
