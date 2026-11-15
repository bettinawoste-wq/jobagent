"""Tests für den Profil-Vorschlag.

Die Logik bekommt einen `Store` auf echtem SQLite, `FakeLanguageModel`, das Suchprofil als
Text, eine feste Uhrzeit und die Antwort der Nutzerin übergeben. Über die Kommandozeile
`main` gehen nur die Tests des Zusammenbaus.
"""

import importlib.util
import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import anthropic
import pytest

from jobagent import profile_suggestion
from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModelError
from jobagent.profile_suggestion import (
    ProfileChange,
    apply_changes,
    create_suggestion,
    suggest_and_decide,
)
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
def profile_path(tmp_path: Path) -> Path:
    path = tmp_path / "profile.md"
    path.write_text(_PROFILE, encoding="utf-8")
    return path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "jobagent.db"
    with Store(path) as opened:
        _add_feedback(opened, "a-1")
    return path


@pytest.fixture
def db(db_path: Path) -> Iterator[Store]:
    with Store(db_path) as opened:
        yield opened


def _add_feedback(db: Store, job_ad_id: str) -> None:
    assessment = Assessment(
        score=2, fits=["Python"], misfits=["Zeitarbeit"], gaps=[], summary="Eher nein."
    )
    job_ad = JobAd(id=job_ad_id, title="Consultant", company="KPMG AG", location="M", link="l")
    db.remember_job_ad(job_ad, assessment, date(2026, 11, 8))
    db.save_feedback(job_ad_id, 3, "KPMG ist keine Zeitarbeit", date(2026, 11, 8))


def _answering(answer: str | Exception):
    def ask(_: str) -> str:
        if isinstance(answer, Exception):
            raise answer
        return answer

    return ask


def _decide(
    db: Store,
    profile_path: Path,
    model: FakeLanguageModel,
    answer: str | Exception = "j",
) -> int:
    return suggest_and_decide(
        db=db,
        search_profile=profile_path.read_text(encoding="utf-8"),
        profile_path=profile_path,
        language_model=model,
        ask=_answering(answer),
        now=_NOW,
    )


def _open_feedback(db: Store) -> list[str]:
    return [entry.job_ad_id for entry in db.open_feedback()]


def _backups(profile_path: Path) -> list[Path]:
    return list(profile_path.parent.glob("profile.sicherung-*.md"))


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
        {"aenderungen": "keine Aenderung", "modellfehler": []},
        {"aenderungen": [{"alt": 1, "neu": "b", "grund": "c"}], "modellfehler": []},
        {"aenderungen": [{"alt": "a", "neu": None, "grund": "c"}], "modellfehler": []},
        {"aenderungen": [{"alt": "a", "neu": "b", "grund": ["c"]}], "modellfehler": []},
    ],
)
def test_suggestion_returns_none_on_errors(answer: dict | LanguageModelError) -> None:
    assert create_suggestion(_PROFILE, [_feedback()], FakeLanguageModel(answer)) is None


@pytest.mark.parametrize(
    ("model_errors", "expected"),
    [
        ("KPMG falsch gelesen", ["KPMG falsch gelesen"]),
        ([1, "zwei"], ["1", "zwei"]),
        ({"a-1": "falsch gelesen"}, []),
    ],
)
def test_suggestion_keeps_changes_despite_sloppy_model_errors(
    model_errors: object, expected: list[str]
) -> None:
    answer = {"aenderungen": [_CHANGE], "modellfehler": model_errors}

    suggestion = create_suggestion(_PROFILE, [_feedback()], FakeLanguageModel(answer))

    assert suggestion is not None
    assert len(suggestion.changes) == 1
    assert suggestion.model_errors == expected


def test_accepting_changes_profile_backs_up_and_processes(
    db: Store, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert _decide(db, profile_path, FakeLanguageModel(_suggestion()), "j") == 0

    assert "Beratungsfirmen" in profile_path.read_text(encoding="utf-8")
    backup = profile_path.parent / "profile.sicherung-2026-11-08-150102.md"
    assert backup.read_text(encoding="utf-8") == _PROFILE
    assert _open_feedback(db) == []
    output = capsys.readouterr().out
    assert "-- Zeitarbeit: maximal Score 2\n" in output
    assert "Mehrfach falsch eingeordnet" in output


def test_rejecting_keeps_profile_and_processes(db: Store, profile_path: Path) -> None:
    assert _decide(db, profile_path, FakeLanguageModel(_suggestion()), "n") == 0

    assert profile_path.read_text(encoding="utf-8") == _PROFILE
    assert _backups(profile_path) == []
    assert _open_feedback(db) == []


@pytest.mark.parametrize("answer", ["a", "", "vielleicht", EOFError()])
def test_cancelling_changes_nothing(db: Store, profile_path: Path, answer: str | Exception) -> None:
    assert _decide(db, profile_path, FakeLanguageModel(_suggestion()), answer) == 0

    assert profile_path.read_text(encoding="utf-8") == _PROFILE
    assert _backups(profile_path) == []
    assert _open_feedback(db) == ["a-1"]


def test_only_model_errors_keeps_profile_and_does_not_ask(
    db: Store, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    model = FakeLanguageModel(_suggestion(changes=[], model_errors=["KPMG falsch gelesen"]))

    assert _decide(db, profile_path, model, AssertionError("darf nicht fragen")) == 0

    assert profile_path.read_text(encoding="utf-8") == _PROFILE
    assert _open_feedback(db) == []
    assert "KPMG falsch gelesen" in capsys.readouterr().out


def test_only_unusable_changes_stay_unprocessed(
    db: Store, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    broken = {"alt": "gibt es nicht", "neu": "x", "grund": "g"}

    model = FakeLanguageModel(_suggestion([broken]))

    assert _decide(db, profile_path, model, AssertionError("nicht fragen")) == 1

    assert profile_path.read_text(encoding="utf-8") == _PROFILE
    assert _open_feedback(db) == ["a-1"]
    assert "gibt es nicht" in capsys.readouterr().err


def test_language_model_error_changes_nothing(
    db: Store, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert _decide(db, profile_path, FakeLanguageModel(LanguageModelError("Netz weg"))) == 1

    assert profile_path.read_text(encoding="utf-8") == _PROFILE
    assert _open_feedback(db) == ["a-1"]
    assert "Kein brauchbarer Vorschlag" in capsys.readouterr().err


def test_no_api_call_without_open_feedback(db: Store, profile_path: Path) -> None:
    model = FakeLanguageModel(_suggestion())
    _decide(db, profile_path, model, "n")
    model.requests.clear()

    assert _decide(db, profile_path, model, "n") == 0

    assert model.requests == []


def test_processed_feedback_is_not_sent_again(db: Store, profile_path: Path) -> None:
    model = FakeLanguageModel(_suggestion([]))
    _decide(db, profile_path, model, "n")
    _add_feedback(db, "a-2")
    model.requests.clear()

    _decide(db, profile_path, model, "n")

    text = _sent_text(model)
    assert '"anzeige_id": "a-2"' in text
    assert '"anzeige_id": "a-1"' not in text


# Zusammenbau


def test_main_suggests_from_profile_file_and_database(
    db_path: Path, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    model = FakeLanguageModel(_suggestion())

    exit_code = profile_suggestion.main(
        db_path=db_path,
        profile_path=profile_path,
        language_model=model,
        ask=_answering("j"),
        now=_NOW,
    )

    assert exit_code == 0
    assert f"Suchprofil:\n{_PROFILE}" in _sent_text(model)
    assert "Beratungsfirmen" in profile_path.read_text(encoding="utf-8")
    assert "profile.sicherung-2026-11-08-150102.md" in capsys.readouterr().out
    with Store(db_path) as db:
        assert _open_feedback(db) == []


def test_missing_profile_is_error(
    db_path: Path, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    profile_path.unlink()
    model = FakeLanguageModel(_suggestion())

    exit_code = profile_suggestion.main(
        db_path=db_path, profile_path=profile_path, language_model=model, now=_NOW
    )

    assert exit_code == 1
    assert model.requests == []
    assert "profile.md nicht gefunden" in capsys.readouterr().err


def test_main_aborts_with_message_when_database_is_unusable(
    tmp_path: Path, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    folder = tmp_path / "jobagent.db"
    folder.mkdir()
    model = FakeLanguageModel(_suggestion())

    exit_code = profile_suggestion.main(
        db_path=folder, profile_path=profile_path, language_model=model, now=_NOW
    )

    assert exit_code == 1
    error = capsys.readouterr().err
    assert error.startswith(f"Fehler: Datenbank {folder} nicht nutzbar")
    assert "Traceback" not in error


class _RecordingClient:
    """Nachgebauter Anthropic-Client, der die Anfrage festhält und dann scheitert."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.messages = _RecordingMessages(self, "messages")
        self.beta = type("Beta", (), {"messages": _RecordingMessages(self, "beta")})()


class _RecordingMessages:
    def __init__(self, client: _RecordingClient, endpoint: str) -> None:
        self._client = client
        self._endpoint = endpoint

    def create(self, **kwargs: object) -> None:
        self._client.requests.append((self._endpoint, kwargs))
        raise anthropic.AnthropicError("nur aufgezeichnet")


def test_suggestion_language_model_asks_sonnet_for_json_answer() -> None:
    client = _RecordingClient()

    with pytest.raises(LanguageModelError):
        profile_suggestion.suggestion_language_model(client=client).ask(
            "System", "Text", {"type": "object"}
        )

    [(endpoint, request)] = client.requests
    assert endpoint == "beta"
    assert request["model"] == "claude-sonnet-5-5"
    assert request["max_tokens"] == 16000
    assert request["output_config"] == {
        "format": {"type": "json_schema", "schema": {"type": "object"}}
    }


def test_old_module_name_is_gone() -> None:
    assert importlib.util.find_spec("jobagent.profilvorschlag") is None
