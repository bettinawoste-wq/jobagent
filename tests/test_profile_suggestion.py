"""Tests für den Profil-Vorschlag.

Die Logik bekommt einen `Store` auf echtem SQLite, `FakeLanguageModel`, das Suchprofil als
Text, eine feste Uhrzeit und die Antwort der Nutzerin übergeben. Über die Kommandozeile
`main` gehen nur die Tests des Zusammenbaus.
"""

import errno
import importlib.util
import json
import os
import stat
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import cast

import anthropic
import pytest

from jobagent import profile_suggestion
from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModelError
from jobagent.profile_suggestion import (
    AcceptedSuggestion,
    AppliedChanges,
    Decision,
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
    return _decision(db, profile_path, model, answer).exit_code


def _decision(
    db: Store,
    profile_path: Path,
    model: FakeLanguageModel,
    answer: str | Exception = "j",
) -> Decision:
    return suggest_and_decide(
        db=db,
        search_profile=profile_path.read_text(encoding="utf-8"),
        profile_name=profile_path.name,
        language_model=model,
        ask=_answering(answer),
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
    result = apply_changes("a\nb\nc\n", [_change("b", "B")])

    assert result == AppliedChanges(
        "a\nB\nc\n", applied=[_change("b", "B")], unusable=[], duplicates=[]
    )


def test_apply_changes_skips_missing_excerpt() -> None:
    change = _change("fehlt", "x")

    assert apply_changes("a\n", [change]) == AppliedChanges(
        "a\n", applied=[], unusable=[change], duplicates=[]
    )


def test_apply_changes_skips_ambiguous_excerpt() -> None:
    change = _change("a", "x")

    assert apply_changes("a a\n", [change]) == AppliedChanges(
        "a a\n", applied=[], unusable=[change], duplicates=[]
    )


def test_apply_changes_skips_empty_excerpt() -> None:
    change = _change("", "x")

    assert apply_changes("a\n", [change]) == AppliedChanges(
        "a\n", applied=[], unusable=[change], duplicates=[]
    )


def test_apply_changes_applies_several_changes_in_order() -> None:
    result = apply_changes("a\nb\n", [_change("a", "A"), _change("b", "B")])

    assert result.text == "A\nB\n"


def test_apply_changes_applies_the_same_change_only_once() -> None:
    # Eine Ergänzung enthält ihren Auszug wieder; doppelt angewandt stünde sie zweimal da.
    change = _change("- Python", "- Python, gern FastAPI")
    again = ProfileChange(old="- Python", new="- Python, gern FastAPI", reason="anders begründet")

    result = apply_changes("- Python\n", [change, again])

    assert result.text == "- Python, gern FastAPI\n"
    assert result.duplicates == [again]
    assert result.unusable == []


def test_apply_changes_checks_excerpt_against_profile_before_suggestion() -> None:
    # "b" steht erst nach der ersten Änderung im Text, nicht im Suchprofil davor.
    later = _change("b", "B")

    result = apply_changes("a\n", [_change("a", "a b"), later])

    assert result.text == "a b\n"
    assert result.unusable == [later]


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


def test_suggestion_replaces_lone_surrogates() -> None:
    # Ein halbes Emoji ließe Anzeige und Speichern des Suchprofils scheitern.
    change = {"alt": "- Zeitarbeit", "neu": "- Zeitarbeit \ud83d", "grund": "g \udc00"}
    model = FakeLanguageModel(_suggestion([change], model_errors=["KPMG \ud83d"]))

    suggestion = create_suggestion(_PROFILE, [_feedback()], model)

    assert suggestion is not None
    assert suggestion.changes == [
        ProfileChange(old="- Zeitarbeit", new="- Zeitarbeit ?", reason="g ?")
    ]
    assert suggestion.model_errors == ["KPMG ?"]


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


def test_accepting_returns_new_profile_and_leaves_saving_to_main(
    db: Store, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    decision = _decision(db, profile_path, FakeLanguageModel(_suggestion()), "j")

    assert decision.exit_code == 0
    new_profile = (
        "# Suchprofil\n\n## Ausschlüsse\n- Zeitarbeit: maximal Score 2 "
        "(Beratungsfirmen zählen nicht)\n"
    )
    assert decision.accepted == AcceptedSuggestion(new_profile, ["a-1"])
    # Speichern und als verarbeitet markieren macht erst der Zusammenbau.
    assert profile_path.read_text(encoding="utf-8") == _PROFILE
    assert _backups(profile_path) == []
    assert _open_feedback(db) == ["a-1"]
    output = capsys.readouterr().out
    assert "-- Zeitarbeit: maximal Score 2\n" in output
    assert "Mehrfach falsch eingeordnet" in output


def test_duplicate_change_is_applied_once_and_shown_as_skipped(
    db: Store, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    decision = _decision(db, profile_path, FakeLanguageModel(_suggestion([_CHANGE, _CHANGE])))

    assert decision.accepted is not None
    assert decision.accepted.new_search_profile == (
        "# Suchprofil\n\n## Ausschlüsse\n- Zeitarbeit: maximal Score 2 "
        "(Beratungsfirmen zählen nicht)\n"
    )
    output = capsys.readouterr()
    assert f"Übersprungen, doppelte Änderung: {_CHANGE['alt']}" in output.err
    assert "nicht eindeutig" not in output.err
    assert output.out.count("Mehrfach falsch eingeordnet") == 1


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
    backup = profile_path.parent / "profile.sicherung-2026-11-08-150102.md"
    assert backup.read_text(encoding="utf-8") == _PROFILE
    assert backup.name in capsys.readouterr().out
    with Store(db_path) as db:
        assert _open_feedback(db) == []


def _accept_in_main(db_path: Path, profile_path: Path) -> int:
    return profile_suggestion.main(
        db_path=db_path,
        profile_path=profile_path,
        language_model=FakeLanguageModel(_suggestion()),
        ask=_answering("j"),
        now=_NOW,
    )


def _assert_aborted_unchanged(
    exit_code: int, db_path: Path, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert exit_code == 1
    error = capsys.readouterr().err
    assert error.startswith(f"Fehler: Suchprofil {profile_path} ließ sich nicht ändern")
    assert "Traceback" not in error
    assert profile_path.read_text(encoding="utf-8") == _PROFILE
    with Store(db_path) as db:
        assert _open_feedback(db) == ["a-1"]


def test_main_aborts_when_backup_cannot_be_written(
    db_path: Path, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    (profile_path.parent / "profile.sicherung-2026-11-08-150102.md").mkdir()

    exit_code = _accept_in_main(db_path, profile_path)

    _assert_aborted_unchanged(exit_code, db_path, profile_path, capsys)


def test_main_aborts_when_profile_cannot_be_replaced(
    db_path: Path,
    profile_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Etwa unter Windows, wenn ein Editor profile.md gesperrt hält.
    def locked(self: Path, target: Path) -> Path:
        raise PermissionError(errno.EACCES, "Zugriff verweigert")

    monkeypatch.setattr(Path, "replace", locked)

    exit_code = _accept_in_main(db_path, profile_path)

    _assert_aborted_unchanged(exit_code, db_path, profile_path, capsys)
    assert sorted(path.name for path in profile_path.parent.iterdir()) == [
        "jobagent.db",
        "profile.md",
    ]


def test_main_aborts_when_new_profile_cannot_be_written(
    db_path: Path,
    profile_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Das neue Suchprofil entsteht erst daneben und ersetzt profile.md dann in einem Schritt;
    # scheitert schon das Schreiben, bleibt profile.md ganz und nichts Halbes liegt herum.
    fsync = os.fsync
    calls = []

    def disk_fails_on_new_profile(fd: int) -> None:
        calls.append(fd)
        if len(calls) == 2:  # erst die Sicherung, dann das neue Suchprofil
            raise OSError(errno.EIO, "Ein-/Ausgabefehler")
        fsync(fd)

    monkeypatch.setattr(os, "fsync", disk_fails_on_new_profile)

    exit_code = _accept_in_main(db_path, profile_path)

    _assert_aborted_unchanged(exit_code, db_path, profile_path, capsys)
    assert sorted(path.name for path in profile_path.parent.iterdir()) == [
        "jobagent.db",
        "profile.md",
    ]


@pytest.mark.skipif(os.name != "nt" and os.geteuid() == 0, reason="root darf alles schreiben")
def test_main_keeps_write_protected_profile(
    db_path: Path, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    profile_path.chmod(stat.S_IREAD)
    try:
        exit_code = _accept_in_main(db_path, profile_path)
        mode = profile_path.stat().st_mode
    finally:
        profile_path.chmod(stat.S_IREAD | stat.S_IWRITE)

    assert not mode & stat.S_IWRITE
    assert _backups(profile_path) == []
    _assert_aborted_unchanged(exit_code, db_path, profile_path, capsys)


@pytest.mark.skipif(os.name == "nt", reason="Windows kennt nur den Schreibschutz als Recht")
def test_main_keeps_mode_of_profile(db_path: Path, profile_path: Path) -> None:
    profile_path.chmod(0o640)  # anders als 0o600, das mkstemp ohnehin vergibt

    assert _accept_in_main(db_path, profile_path) == 0

    assert stat.S_IMODE(profile_path.stat().st_mode) == 0o640


def test_main_writes_through_symlinked_profile(
    tmp_path: Path, db_path: Path, profile_path: Path
) -> None:
    link = tmp_path / "verknuepft" / "profile.md"
    link.parent.mkdir()
    try:
        link.symlink_to(profile_path)
    except OSError:
        pytest.skip("Symlinks sind hier nicht erlaubt")

    assert _accept_in_main(db_path, link) == 0

    assert link.is_symlink()
    assert "Beratungsfirmen" in profile_path.read_text(encoding="utf-8")
    assert len(_backups(profile_path)) == 1  # neben der Datei, nicht neben der Verknüpfung


def test_main_shows_log_on_console(
    db_path: Path, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    model = FakeLanguageModel(LanguageModelError("Netz weg"))

    profile_suggestion.main(
        db_path=db_path, profile_path=profile_path, language_model=model, now=_NOW
    )

    error = capsys.readouterr().err
    assert "ERROR:jobagent.profile_suggestion:Sprachmodell für den Profil-Vorschlag" in error


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


def test_unreadable_profile_is_error(
    db_path: Path, profile_path: Path, capsys: pytest.CaptureFixture
) -> None:
    profile_path.write_bytes("Suchprofil für München".encode("cp1252"))
    model = FakeLanguageModel(_suggestion())

    exit_code = profile_suggestion.main(
        db_path=db_path, profile_path=profile_path, language_model=model, now=_NOW
    )

    assert exit_code == 1
    assert model.requests == []
    error = capsys.readouterr().err
    assert error.startswith(f"Fehler: Suchprofil {profile_path} ist nicht in UTF-8 gespeichert")
    assert "Traceback" not in error


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

    def as_anthropic(self) -> anthropic.Anthropic:
        # Nachgebaut sind nur messages und beta.messages, mehr nutzen die Adapter nicht.
        return cast(anthropic.Anthropic, self)


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
        profile_suggestion.suggestion_language_model(client=client.as_anthropic()).ask(
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
