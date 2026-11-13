"""Tests fuer den Profil-Vorschlag, das Sprachmodell ist durch FakeLanguageModel ersetzt."""

import importlib.util
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from jobagent import profile_suggestion
from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModelError
from jobagent.profile_suggestion import ProfileChange, apply_changes, create_suggestion
from jobagent.score import Assessment
from jobagent.store import Feedback, Store
from tests.fakes import FakeLanguageModel

_PROFILE = "# Suchprofil\n\n## Ausschlüsse\n- Zeitarbeit: maximal Score 2\n"
_NOW = datetime(2026, 11, 8, 15, 1, 2)
_CHANGE = {
    "alt": "- Zeitarbeit: maximal Score 2",
    "neu": "- Zeitarbeit: maximal Score 2 (Beratungsfirmen zählen nicht)",
    "grund": "Mehrfach falsch eingeordnet",
}


def _suggestion(changes: list[dict] | None = None, model_errors: list[str] | None = None) -> dict:
    return {
        "aenderungen": [_CHANGE] if changes is None else changes,
        "modellfehler": model_errors or [],
    }


def _sent_text(model: FakeLanguageModel) -> str:
    return model.requests[0].text


@pytest.fixture
def project(tmp_path: Path) -> dict[str, Path]:
    db = tmp_path / "jobagent.db"
    profile = tmp_path / "profile.md"
    profile.write_text(_PROFILE, encoding="utf-8")
    _add_feedback(db, "a-1")
    return {"db_path": db, "profile_path": profile}


def _add_feedback(db: Path, job_ad_id: str) -> None:
    assessment = Assessment(
        score=2, fits=["Python"], misfits=["Zeitarbeit"], gaps=[], summary="Eher nein."
    )
    job_ad = JobAd(id=job_ad_id, title="Consultant", company="KPMG AG", location="M", link="l")
    with Store(db) as opened:
        opened.remember_job_ad(job_ad, assessment, date(2026, 11, 8))
        opened.save_feedback(job_ad_id, 3, "KPMG ist keine Zeitarbeit", date(2026, 11, 8))


def _run(project: dict[str, Path], model: FakeLanguageModel, answer: str | Exception = "j") -> int:
    def ask(_: str) -> str:
        if isinstance(answer, Exception):
            raise answer
        return answer

    return profile_suggestion.main(**project, language_model=model, ask=ask, now=_NOW)


def _processed(project: dict[str, Path]) -> list[int]:
    conn = sqlite3.connect(project["db_path"])
    try:
        return [
            row[0] for row in conn.execute("SELECT verarbeitet FROM feedback ORDER BY anzeige_id")
        ]
    finally:
        conn.close()


def _backups(project: dict[str, Path]) -> list[Path]:
    return list(project["profile_path"].parent.glob("profile.sicherung-*.md"))


def _change(old: str, new: str) -> ProfileChange:
    return ProfileChange(old=old, new=new, reason="g")


def _feedback() -> Feedback:
    return Feedback(
        job_ad_id="a-1",
        title="Consultant",
        company="KPMG AG",
        model_score=2,
        assessment=Assessment(
            score=2, fits=["Python"], misfits=["Zeitarbeit"], gaps=[], summary="Eher nein."
        ),
        own_score=3,
        reason="KPMG ist keine Zeitarbeit",
    )


def test_suggestion_sends_feedback_with_german_keys() -> None:
    without_assessment = Feedback(
        job_ad_id="a-0",
        title="Alt",
        company=None,
        model_score=1,
        assessment=None,
        own_score=2,
        reason=None,
    )
    model = FakeLanguageModel(_suggestion())

    create_suggestion(_PROFILE, [without_assessment, _feedback()], model)

    text = _sent_text(model)
    data = json.loads(text.split("Rueckmeldungen:\n", 1)[1])
    assert data == [
        {
            "anzeige_id": "a-0",
            "titel": "Alt",
            "firma": None,
            "modell_score": 1,
            "bewertung": {},
            "eigener_score": 2,
            "grund": None,
        },
        {
            "anzeige_id": "a-1",
            "titel": "Consultant",
            "firma": "KPMG AG",
            "modell_score": 2,
            "bewertung": {
                "passt": ["Python"],
                "passt_nicht": ["Zeitarbeit"],
                "luecken": [],
                "kurzfazit": "Eher nein.",
            },
            "eigener_score": 3,
            "grund": "KPMG ist keine Zeitarbeit",
        },
    ]
    assert list(data[1]) == list(data[0])
    assert list(data[1]["bewertung"]) == ["passt", "passt_nicht", "luecken", "kurzfazit"]


def test_apply_changes_replaces_exactly_the_excerpt() -> None:
    new, skipped = apply_changes("a\nb\nc\n", [_change("b", "B")])

    assert new == "a\nB\nc\n"
    assert skipped == []


def test_apply_changes_skips_missing_excerpt() -> None:
    change = _change("fehlt", "x")

    assert apply_changes("a\n", [change]) == ("a\n", [change])


def test_apply_changes_skips_ambiguous_excerpt() -> None:
    change = _change("a", "x")

    assert apply_changes("a a\n", [change]) == ("a a\n", [change])


def test_apply_changes_skips_empty_excerpt() -> None:
    change = _change("", "x")

    assert apply_changes("a\n", [change]) == ("a\n", [change])


def test_apply_changes_applies_several_changes_in_order() -> None:
    new, _ = apply_changes("a\nb\n", [_change("a", "A"), _change("b", "B")])

    assert new == "A\nB\n"


def test_suggestion_asks_for_changes_and_model_errors() -> None:
    model = FakeLanguageModel(_suggestion())

    create_suggestion(_PROFILE, [_feedback()], model)

    schema = model.requests[0].schema
    assert schema["required"] == ["aenderungen", "modellfehler"]
    assert schema["properties"]["aenderungen"]["items"]["required"] == ["alt", "neu", "grund"]


def test_suggestion_sends_profile_and_feedback() -> None:
    model = FakeLanguageModel(_suggestion())

    create_suggestion(_PROFILE, [_feedback()], model)

    text = _sent_text(model)
    assert _PROFILE in text
    assert "KPMG ist keine Zeitarbeit" in text
    assert '"modell_score": 2' in text
    assert '"eigener_score": 3' in text
    assert "Zeitarbeit" in text


def test_suggestion_is_parsed() -> None:
    model = FakeLanguageModel(_suggestion(model_errors=["KPMG falsch gelesen"]))

    suggestion = create_suggestion(_PROFILE, [_feedback()], model)

    assert suggestion is not None
    assert suggestion.changes == [
        ProfileChange(old=_CHANGE["alt"], new=_CHANGE["neu"], reason=_CHANGE["grund"])
    ]
    assert suggestion.model_errors == ["KPMG falsch gelesen"]


@pytest.mark.parametrize(
    "answer",
    [
        LanguageModelError("Anthropic-API-Anfrage fehlgeschlagen"),
        {"modellfehler": []},
        {"aenderungen": [{"alt": "a", "neu": "b"}], "modellfehler": []},
        {"aenderungen": ["keine Aenderung"], "modellfehler": []},
    ],
)
def test_suggestion_returns_none_on_errors(answer: dict | LanguageModelError) -> None:
    assert create_suggestion(_PROFILE, [_feedback()], FakeLanguageModel(answer)) is None


def test_accepting_changes_profile_backs_up_and_processes(
    project: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    assert _run(project, FakeLanguageModel(_suggestion()), "j") == 0

    assert "Beratungsfirmen" in project["profile_path"].read_text(encoding="utf-8")
    backup = project["profile_path"].parent / "profile.sicherung-2026-11-08-150102.md"
    assert backup.read_text(encoding="utf-8") == _PROFILE
    assert _processed(project) == [1]
    output = capsys.readouterr().out
    assert "-- Zeitarbeit: maximal Score 2\n" in output
    assert "Mehrfach falsch eingeordnet" in output


def test_rejecting_keeps_profile_and_processes(project: dict[str, Path]) -> None:
    assert _run(project, FakeLanguageModel(_suggestion()), "n") == 0

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _backups(project) == []
    assert _processed(project) == [1]


@pytest.mark.parametrize("answer", ["a", "", "vielleicht", EOFError()])
def test_cancelling_changes_nothing(project: dict[str, Path], answer: str | Exception) -> None:
    assert _run(project, FakeLanguageModel(_suggestion()), answer) == 0

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _backups(project) == []
    assert _processed(project) == [0]


def test_only_model_errors_keeps_profile_and_does_not_ask(
    project: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    model = FakeLanguageModel(_suggestion(changes=[], model_errors=["KPMG falsch gelesen"]))

    assert _run(project, model, AssertionError("darf nicht fragen")) == 0

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _processed(project) == [1]
    assert "KPMG falsch gelesen" in capsys.readouterr().out


def test_only_unusable_changes_stay_unprocessed(
    project: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    broken = {"alt": "gibt es nicht", "neu": "x", "grund": "g"}

    model = FakeLanguageModel(_suggestion([broken]))

    assert _run(project, model, AssertionError("nicht fragen")) == 1

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _processed(project) == [0]
    assert "gibt es nicht" in capsys.readouterr().err


def test_language_model_error_changes_nothing(
    project: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    assert _run(project, FakeLanguageModel(LanguageModelError("Netz weg"))) == 1

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _processed(project) == [0]
    assert "Kein brauchbarer Vorschlag" in capsys.readouterr().err


def test_no_api_call_without_open_feedback(project: dict[str, Path]) -> None:
    model = FakeLanguageModel(_suggestion())
    _run(project, model, "n")
    model.requests.clear()

    assert _run(project, model, "n") == 0

    assert model.requests == []


def test_processed_feedback_is_not_sent_again(project: dict[str, Path]) -> None:
    model = FakeLanguageModel(_suggestion([]))
    _run(project, model, "n")
    _add_feedback(project["db_path"], "a-2")
    model.requests.clear()

    _run(project, model, "n")

    text = _sent_text(model)
    assert '"anzeige_id": "a-2"' in text
    assert '"anzeige_id": "a-1"' not in text


def test_without_language_model_sonnet_is_built_for_json_answers(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[tuple[str, dict]] = []
    sonnet = FakeLanguageModel(_suggestion())
    real_class = profile_suggestion.AnthropicLanguageModel

    def build(model: str, **options: object) -> FakeLanguageModel:
        built.append((model, options))
        real_class(model, **options)  # die Optionen passen zur echten Signatur
        return sonnet

    monkeypatch.setattr(profile_suggestion, "AnthropicLanguageModel", build)

    assert profile_suggestion.main(**project, ask=lambda _: "n", now=_NOW) == 0

    assert built == [("claude-sonnet-5-5", {"max_tokens": 16000, "json_answer": True})]
    assert len(sonnet.requests) == 1


def test_old_module_name_is_gone() -> None:
    assert importlib.util.find_spec("jobagent.profilvorschlag") is None


def test_missing_profile_is_error(project: dict[str, Path]) -> None:
    project["profile_path"].unlink()
    model = FakeLanguageModel(_suggestion())

    assert _run(project, model) == 1

    assert model.requests == []
