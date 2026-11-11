"""Tests fuer den Profil-Vorschlag, die Anthropic-API ist vollstaendig gemockt."""

import importlib.util
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

from jobagent import profile_suggestion, store
from jobagent.job_ad import JobAd
from jobagent.profile_suggestion import ProfileChange, apply_changes, create_suggestion
from jobagent.score import Assessment

_PROFILE = "# Suchprofil\n\n## Ausschlüsse\n- Zeitarbeit: maximal Score 2\n"
_NOW = datetime(2026, 11, 8, 15, 1, 2)
_CHANGE = {
    "alt": "- Zeitarbeit: maximal Score 2",
    "neu": "- Zeitarbeit: maximal Score 2 (Beratungsfirmen zählen nicht)",
    "grund": "Mehrfach falsch eingeordnet",
}


class _FakeClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _response(data: object, stop_reason: str = "end_turn") -> SimpleNamespace:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=text)],
    )


def _suggestion(changes: list[dict] | None = None, model_errors: list[str] | None = None):
    return _response(
        {
            "aenderungen": [_CHANGE] if changes is None else changes,
            "modellfehler": model_errors or [],
        }
    )


def _api_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]


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
    conn = store.connect(db)
    store.mark_seen(conn, job_ad, assessment, date(2026, 11, 8))
    store.save_feedback(conn, job_ad_id, 3, "KPMG ist keine Zeitarbeit", date(2026, 11, 8))
    conn.close()


def _run(project: dict[str, Path], client: _FakeClient, answer: str | Exception = "j") -> int:
    def ask(_: str) -> str:
        if isinstance(answer, Exception):
            raise answer
        return answer

    return profile_suggestion.main(**project, client=client, ask=ask, now=_NOW)


def _processed(project: dict[str, Path]) -> list[int]:
    conn = store.connect(project["db_path"])
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


def _feedback() -> store.Feedback:
    return store.Feedback(
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
    without_assessment = store.Feedback(
        job_ad_id="a-0",
        title="Alt",
        company=None,
        model_score=1,
        assessment=None,
        own_score=2,
        reason=None,
    )
    client = _FakeClient(_suggestion())

    create_suggestion(_PROFILE, [without_assessment, _feedback()], client=client)

    text = client.calls[0]["messages"][0]["content"]
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


def test_suggestion_uses_sonnet_with_structured_output() -> None:
    client = _FakeClient(_suggestion())

    create_suggestion(_PROFILE, [_feedback()], client=client)

    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert "tool_choice" not in call
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]


def test_suggestion_sends_profile_and_feedback() -> None:
    client = _FakeClient(_suggestion())

    create_suggestion(_PROFILE, [_feedback()], client=client)

    text = client.calls[0]["messages"][0]["content"]
    assert _PROFILE in text
    assert "KPMG ist keine Zeitarbeit" in text
    assert '"modell_score": 2' in text
    assert '"eigener_score": 3' in text
    assert "Zeitarbeit" in text


def test_suggestion_is_parsed() -> None:
    client = _FakeClient(_suggestion(model_errors=["KPMG falsch gelesen"]))

    suggestion = create_suggestion(_PROFILE, [_feedback()], client=client)

    assert suggestion is not None
    assert suggestion.changes == [
        ProfileChange(old=_CHANGE["alt"], new=_CHANGE["neu"], reason=_CHANGE["grund"])
    ]
    assert suggestion.model_errors == ["KPMG falsch gelesen"]


@pytest.mark.parametrize(
    "response",
    [
        _api_error(),
        TypeError("Could not resolve authentication method."),
        _response({"modellfehler": []}),
        _response("kein json"),
        _response({"aenderungen": [], "modellfehler": []}, stop_reason="refusal"),
        _response({"aenderungen": [], "modellfehler": []}, stop_reason="max_tokens"),
        SimpleNamespace(stop_reason="end_turn", content=[]),
    ],
)
def test_suggestion_returns_none_on_errors(response: object) -> None:
    assert create_suggestion(_PROFILE, [_feedback()], client=_FakeClient(response)) is None


def test_accepting_changes_profile_backs_up_and_processes(
    project: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    assert _run(project, _FakeClient(_suggestion()), "j") == 0

    assert "Beratungsfirmen" in project["profile_path"].read_text(encoding="utf-8")
    backup = project["profile_path"].parent / "profile.sicherung-2026-11-08-150102.md"
    assert backup.read_text(encoding="utf-8") == _PROFILE
    assert _processed(project) == [1]
    output = capsys.readouterr().out
    assert "-- Zeitarbeit: maximal Score 2\n" in output
    assert "Mehrfach falsch eingeordnet" in output


def test_rejecting_keeps_profile_and_processes(project: dict[str, Path]) -> None:
    assert _run(project, _FakeClient(_suggestion()), "n") == 0

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _backups(project) == []
    assert _processed(project) == [1]


@pytest.mark.parametrize("answer", ["a", "", "vielleicht", EOFError()])
def test_cancelling_changes_nothing(project: dict[str, Path], answer: str | Exception) -> None:
    assert _run(project, _FakeClient(_suggestion()), answer) == 0

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _backups(project) == []
    assert _processed(project) == [0]


def test_only_model_errors_keeps_profile_and_does_not_ask(
    project: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    client = _FakeClient(_suggestion(changes=[], model_errors=["KPMG falsch gelesen"]))

    assert _run(project, client, AssertionError("darf nicht fragen")) == 0

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _processed(project) == [1]
    assert "KPMG falsch gelesen" in capsys.readouterr().out


def test_only_unusable_changes_stay_unprocessed(
    project: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    broken = {"alt": "gibt es nicht", "neu": "x", "grund": "g"}

    assert _run(project, _FakeClient(_suggestion([broken])), AssertionError("nicht fragen")) == 1

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _processed(project) == [0]
    assert "gibt es nicht" in capsys.readouterr().err


def test_api_error_changes_nothing(project: dict[str, Path]) -> None:
    assert _run(project, _FakeClient(_api_error())) == 1

    assert project["profile_path"].read_text(encoding="utf-8") == _PROFILE
    assert _processed(project) == [0]


def test_no_api_call_without_open_feedback(project: dict[str, Path]) -> None:
    client = _FakeClient(_suggestion())
    _run(project, client, "n")
    client.calls.clear()

    assert _run(project, client, "n") == 0

    assert client.calls == []


def test_processed_feedback_is_not_sent_again(project: dict[str, Path]) -> None:
    client = _FakeClient(_suggestion([]))
    _run(project, client, "n")
    _add_feedback(project["db_path"], "a-2")
    client.calls.clear()

    _run(project, client, "n")

    text = client.calls[0]["messages"][0]["content"]
    assert '"anzeige_id": "a-2"' in text
    assert '"anzeige_id": "a-1"' not in text


def test_old_module_name_is_gone() -> None:
    assert importlib.util.find_spec("jobagent.profilvorschlag") is None


def test_missing_profile_is_error(project: dict[str, Path]) -> None:
    project["profile_path"].unlink()
    client = _FakeClient(_suggestion())

    assert _run(project, client) == 1

    assert client.calls == []
