"""Tests für main.py: Zusammenbau des Laufs und die eingebauten Quellen.

Das Verhalten des Laufs selbst prüft `tests/test_run.py`. Hier geht ein ganzer Lauf über den
Zusammenbau: Konfiguration und Suchprofil aus Dateien, Fake-Quellen und `FakeLanguageModel`,
aber echtes SQLite und eine echte Report-Datei.
"""

import dataclasses
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import httpx
import pytest

from jobagent import feedback, main, profile_suggestion
from jobagent.anthropic_language_model import AnthropicLanguageModel
from jobagent.config import Config
from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModelError
from jobagent.search_window import SearchWindow
from jobagent.sources.watchlist import WatchlistCompany
from jobagent.store import Store
from tests.fakes import FakeLanguageModel, FakeSource, assessment_answer, fake_job_ad

TODAY = date(2026, 3, 2)

_CONFIG = """
[suche]
was = ["Softwareentwickler", "Data"]
wo = "München"
veroeffentlichtseit = 1

[bundesagentur]
umkreis = 30

[report]
mindest_score = 5
"""

_PROFILE = "# Suchprofil\nPython, München, Hybrid bevorzugt."

_WINDOW = SearchWindow(1, since=None, capped=False)


@pytest.fixture
def project(tmp_path: Path) -> dict[str, Path]:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_CONFIG, encoding="utf-8")
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(_PROFILE, encoding="utf-8")
    return {
        "config_path": config_path,
        "profile_path": profile_path,
        "db_path": tmp_path / "jobagent.db",
        "output_dir": tmp_path / "output",
    }


@pytest.fixture
def no_builtins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Weder eingebaute Quellen noch das eingebaute Sprachmodell dürfen gefragt werden."""

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Eingebaute Quelle darf nicht aufgerufen werden")

    def no_model(*args: object, **kwargs: object) -> None:
        raise AssertionError("Eingebautes Sprachmodell darf nicht gefragt werden")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(AnthropicLanguageModel, "ask", no_model)


def test_main_runs_whole_run_from_files_into_sqlite_and_report(
    project: dict[str, Path], fixed_today: Callable[[date], None], no_builtins: None
) -> None:
    fixed_today(TODAY)
    source = FakeSource([fake_job_ad("a-1"), fake_job_ad("a-2")], name="Quelle A")
    model = FakeLanguageModel(assessment_answer(4), assessment_answer(5))

    path = main.main(**project, sources=[source], language_model=model)

    assert path == project["output_dir"] / "2026-03-02.md"
    content = path.read_text(encoding="utf-8")
    assert "- Quelle A: 2 Anzeigen\n" in content
    assert content.index("## 1. Stelle a-2") < content.index("## Weitere Treffer (Score unter 5)")
    assert "- **2.** Stelle a-1" in content
    assert source.received == [["Softwareentwickler", "Data"]]
    assert all(_PROFILE in request.text for request in model.requests)
    with Store(project["db_path"]) as db:
        match = db.find_match("2026-03-02", 1)
        assert match is not None
        assert match.id == "a-2"
        assert not db.is_new("a-1")


def test_main_reads_search_profile_with_bom_without_the_bom(
    project: dict[str, Path], fixed_today: Callable[[date], None], no_builtins: None
) -> None:
    fixed_today(TODAY)
    project["profile_path"].write_text(_PROFILE, encoding="utf-8-sig")
    model = FakeLanguageModel(assessment_answer(4))

    main.main(**project, sources=[FakeSource([fake_job_ad("a-1")])], language_model=model)

    assert chr(0xFEFF) not in model.requests[0].text  # kein BOM
    assert _PROFILE in model.requests[0].text


def test_main_keeps_seen_job_ads_in_database_between_runs(
    project: dict[str, Path], fixed_today: Callable[[date], None], no_builtins: None
) -> None:
    fixed_today(TODAY)
    source = FakeSource([fake_job_ad("a-1")])
    model = FakeLanguageModel(assessment_answer(4))

    main.main(**project, sources=[source], language_model=model)
    second_run = main.main(**project, sources=[source], language_model=model)

    assert len(model.requests) == 1
    assert second_run.name == "2026-03-02-2.md"
    assert "Keine neuen Treffer" in second_run.read_text(encoding="utf-8")


def _broken_toml(folder: Path) -> None:
    (folder / "config.toml").write_text('[suche]\nwas = ["offen', encoding="utf-8")


def _misplaced_key(folder: Path) -> None:
    (folder / "config.toml").write_text('was = ["Data"]\n', encoding="utf-8")


def _no_config(folder: Path) -> None:
    (folder / "config.toml").unlink()


def _no_profile(folder: Path) -> None:
    (folder / "profile.md").unlink()


def _database_is_folder(folder: Path) -> None:
    (folder / "jobagent.db").mkdir()


def _lock_file_is_folder(folder: Path) -> None:
    (folder / "jobagent.db.runlock").mkdir()


def _output_is_file(folder: Path) -> None:
    (folder / "output").write_text("kein Ordner", encoding="utf-8")


@pytest.mark.parametrize(
    ("breakage", "message"),
    [
        (_broken_toml, "Fehler: config.toml ist kein gültiges TOML"),
        (_misplaced_key, "Fehler: config.toml ist ungültig"),
        (_no_config, "Fehler: config.toml nicht gefunden"),
        (_no_profile, "Fehler: Suchprofil profile.md nicht gefunden"),
        (_database_is_folder, "Fehler: Datenbank jobagent.db nicht nutzbar"),
        (_output_is_file, "Fehler: Report lässt sich nicht in output schreiben"),
        (_lock_file_is_folder, "Fehler: Sperrdatei jobagent.db.runlock nicht nutzbar"),
    ],
)
def test_cli_aborts_with_message_and_exit_code_1(
    breakage: Callable[[Path], None],
    message: str,
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    no_builtins: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "default_sources", lambda config, search_window: [FakeSource()])
    breakage(tmp_path)
    caplog.set_level(logging.DEBUG)

    exit_code = main.cli([])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert err.startswith(message)
    assert "Traceback" not in err
    [logged] = [record for record in caplog.records if record.getMessage() == "Abgebrochen"]
    assert logged.exc_info  # der Traceback steht nur im Log


def test_cli_returns_exit_code_0_after_run(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_today: Callable[[date], None],
    no_builtins: None,
) -> None:
    fixed_today(TODAY)  # arbeitet auch in tmp_path
    monkeypatch.setattr(main, "default_sources", lambda config, search_window: [FakeSource()])

    assert main.cli([]) == 0
    assert (tmp_path / "output" / "2026-03-02.md").exists()


def test_cli_writes_log_file_named_like_its_report(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_today: Callable[[date], None],
    no_builtins: None,
) -> None:
    fixed_today(TODAY)
    source = FakeSource([fake_job_ad("a-1")])
    monkeypatch.setattr(main, "default_sources", lambda config, search_window: [source])
    model = FakeLanguageModel(LanguageModelError("Zeitüberschreitung"))
    monkeypatch.setattr(main, "AnthropicToolLanguageModel", lambda model_name: model)

    main.cli([])
    main.cli([])

    output = tmp_path / "output"
    assert sorted(path.name for path in output.iterdir()) == [
        "2026-03-02-2.log",
        "2026-03-02-2.md",
        "2026-03-02.log",
        "2026-03-02.md",
    ]
    log = (output / "2026-03-02.log").read_text(encoding="utf-8")
    assert "Anzeige unbewertet, der nächste Lauf versucht es erneut (anzeige='a-1')" in log


def test_default_sources_are_bundesagentur_and_arbeitnow() -> None:
    names = [source.name for source in main.default_sources(Config(), _WINDOW)]

    assert names == ["Bundesagentur für Arbeit", "Arbeitnow"]


def test_default_sources_include_watchlist_with_companies_from_config() -> None:
    config = Config(companies=[WatchlistCompany(name="GitLab", ats="greenhouse", slug="gitlab")])

    names = [source.name for source in main.default_sources(config, _WINDOW)]

    assert names == ["Bundesagentur für Arbeit", "Arbeitnow", "Firmen-Watchlist"]


def test_default_sources_search_with_location_radius_and_search_window() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "greenhouse" in request.url.host:
            return httpx.Response(200, json={"jobs": []})
        if "arbeitnow" in request.url.host:
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"ergebnisliste": []})

    config = Config(
        keywords=["Python"],
        location="München",
        radius=30,
        published_since=7,
        companies=[WatchlistCompany(name="GitLab", ats="greenhouse", slug="gitlab")],
    )
    window = SearchWindow(4, since=date(2026, 2, 27), capped=False)

    for source in main.default_sources(config, window, transport=httpx.MockTransport(handler)):
        assert source.search(config.keywords).errors == []

    hosts = [request.url.host for request in requests]
    assert hosts == ["rest.arbeitsagentur.de", "www.arbeitnow.com", "boards-api.greenhouse.io"]
    assert dict(requests[0].url.params) == {
        "was": "Python",
        "wo": "München",
        "umkreis": "30",
        "veroeffentlichtseit": "4",
        "page": "1",
        "size": requests[0].url.params["size"],
    }
    assert dict(requests[2].url.params) == {}  # die Watchlist kennt keinen Suchzeitraum


def test_cli_keeps_traceback_of_abort_in_log_file_not_on_console(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_builtins: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    _no_profile(tmp_path)

    assert main.cli([]) == 1
    assert main.cli([]) == 1

    assert "Traceback" not in capsys.readouterr().err
    assert sorted(path.name for path in (tmp_path / "output").iterdir()) == ["abgebrochen.log"]
    log = (tmp_path / "output" / "abgebrochen.log").read_text(encoding="utf-8")
    assert log.count("DEBUG jobagent.main: Abgebrochen\nTraceback (most recent call last):") == 2
    assert "SearchProfileError: Suchprofil profile.md nicht gefunden" in log


def _aborted_log_of(output: Path, size: int) -> bytes:
    """Legt `abgebrochen.log` mit `size` Bytes älterer Läufe an und gibt den Inhalt zurück."""
    output.mkdir(exist_ok=True)
    line = b"Log alter Laeufe\n"
    content = line * (size // len(line)) + b"x" * (size % len(line))
    (output / "abgebrochen.log").write_bytes(content)
    return content


def test_cli_starts_new_log_of_aborted_runs_when_this_run_would_exceed_the_limit(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_builtins: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    _no_profile(tmp_path)
    output = tmp_path / "output"
    # Knapp unter der Grenze; erst das Log dieses Laufs brächte die Datei darüber.
    old = _aborted_log_of(output, main._ABORTED_LOG_MAX_BYTES - 100)

    assert main.cli([]) == 1

    log = (output / "abgebrochen.log").read_text(encoding="utf-8")
    assert "Log alter Laeufe" not in log
    assert "SearchProfileError: Suchprofil profile.md nicht gefunden" in log
    assert (output / "abgebrochen.log.1").read_bytes() == old


def test_cli_keeps_only_one_older_copy_of_the_log_of_aborted_runs(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_builtins: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    _no_profile(tmp_path)
    output = tmp_path / "output"
    old = _aborted_log_of(output, main._ABORTED_LOG_MAX_BYTES + 100)
    (output / "abgebrochen.log.1").write_text("Log uralter Läufe\n", encoding="utf-8")

    assert main.cli([]) == 1

    assert sorted(path.name for path in output.iterdir()) == [
        "abgebrochen.log",
        "abgebrochen.log.1",
    ]
    assert (output / "abgebrochen.log.1").read_bytes() == old


def test_cli_appends_to_log_of_aborted_runs_below_the_limit(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_builtins: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    _no_profile(tmp_path)
    output = tmp_path / "output"
    old = _aborted_log_of(output, main._ABORTED_LOG_MAX_BYTES // 2)

    assert main.cli([]) == 1

    log = (output / "abgebrochen.log").read_bytes()
    assert log.startswith(old)
    assert b"SearchProfileError: Suchprofil profile.md nicht gefunden" in log
    assert not (output / "abgebrochen.log.1").exists()


def test_cli_keeps_log_of_aborted_runs_when_older_copy_cannot_be_made(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_builtins: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    _no_profile(tmp_path)
    output = tmp_path / "output"
    old = _aborted_log_of(output, main._ABORTED_LOG_MAX_BYTES + 100)
    (output / "abgebrochen.log.1").mkdir()  # die ältere Kopie lässt sich nicht anlegen

    assert main.cli([]) == 1

    log = (output / "abgebrochen.log").read_bytes()
    assert log.startswith(old)
    assert b"SearchProfileError: Suchprofil profile.md nicht gefunden" in log
    assert "Ältere Kopie des Logs ließ sich nicht anlegen" in capsys.readouterr().err


def test_cli_logs_job_ad_ids_but_never_their_full_text(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_today: Callable[[date], None],
    caplog: pytest.LogCaptureFixture,
    no_builtins: None,
) -> None:
    fixed_today(TODAY)
    full_text = "Wir suchen eine Entwicklerin mit Leidenschaft für saubere Daten."
    job_ad = JobAd("a-1", "Stelle a-1", "Beispiel GmbH", "München", "https://example.com/a-1")
    job_ad = dataclasses.replace(job_ad, description=full_text)
    monkeypatch.setattr(
        main, "default_sources", lambda config, search_window: [FakeSource([job_ad])]
    )

    class ChattyLanguageModel(FakeLanguageModel):
        """Loggt wie das SDK von Anthropic die ganze Anfrage auf DEBUG und scheitert dann."""

        def ask(self, system: str, text: str, schema: dict) -> dict:
            logging.getLogger("anthropic._base_client").debug("Request options: %s", text)
            return super().ask(system, text, schema)

    caplog.set_level(logging.DEBUG, logger="anthropic")  # wie mit ANTHROPIC_LOG=debug
    model = ChattyLanguageModel(LanguageModelError(f"Antwort zu: {job_ad.id}"))
    monkeypatch.setattr(main, "AnthropicToolLanguageModel", lambda model_name: model)

    main.cli([])

    assert full_text in model.requests[0].text  # das Sprachmodell hat den Volltext bekommen
    log = (tmp_path / "output" / "2026-03-02.log").read_text(encoding="utf-8")
    assert "anzeige='a-1'" in log
    assert "Leidenschaft" not in log


def test_cli_replaces_stale_log_file_of_a_deleted_report(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_today: Callable[[date], None],
    no_builtins: None,
) -> None:
    fixed_today(TODAY)
    monkeypatch.setattr(main, "default_sources", lambda config, search_window: [FakeSource()])
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "2026-03-02.log").write_text("Log eines alten Laufs", encoding="utf-8")

    main.cli([])

    log = (tmp_path / "output" / "2026-03-02.log").read_text(encoding="utf-8")
    assert "Log eines alten Laufs" not in log


def test_cli_keeps_log_of_unexpected_crash(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_builtins: None,
) -> None:
    monkeypatch.chdir(tmp_path)

    def crash(**kwargs: object) -> Path:
        raise RuntimeError("Programmfehler im Lauf")

    monkeypatch.setattr(main, "run", crash)

    with pytest.raises(RuntimeError):
        main.cli([])

    log = (tmp_path / "output" / "abgebrochen.log").read_text(encoding="utf-8")
    assert "RuntimeError: Programmfehler im Lauf" in log


def test_command_writes_traceback_of_abort_into_log_file(tmp_path: Path) -> None:
    # Eigener Prozess wie `python -m jobagent.main`: Dort heißt der Logger `__main__`.
    unset = {"ANTHROPIC_API_KEY", "ANTHROPIC_LOG"}
    env = {name: value for name, value in os.environ.items() if name not in unset}
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    result = subprocess.run(
        [sys.executable, "-m", "jobagent.main"], cwd=tmp_path, env=env, capture_output=True
    )

    assert result.returncode == 1
    assert b"Traceback" not in result.stderr
    log = (tmp_path / "output" / "abgebrochen.log").read_text(encoding="utf-8")
    assert "Abgebrochen\nTraceback (most recent call last):" in log
    assert "ConfigError: config.toml nicht gefunden" in log


_REPO = Path(__file__).parents[1]

# Ein Lauf in einem eigenen Prozess, dessen Quelle meldet, dass sie sucht, und dann wartet,
# bis auf stdin eine Zeile kommt: "absturz" beendet den Prozess hart, ohne aufzuräumen, jede
# andere lässt den Lauf zu Ende gehen. Er arbeitet mit den Standardpfaden in seinem Arbeitsordner.
# Hart beendet er sich selbst: Unter Windows startet das Python einer venv das eigentliche
# Python als Kindprozess, ein kill() von außen träfe nur den Starter.
_WAITING_RUN = """
import os
import sys
from jobagent import main
from jobagent.sources import SearchResult
from tests.fakes import FakeLanguageModel

class WaitingSource:
    name = "Wartende Quelle"

    def search(self, keywords):
        print("sucht", flush=True)
        if sys.stdin.readline().strip() == "absturz":
            os._exit(1)
        return SearchResult([], [])

main.main(sources=[WaitingSource()], language_model=FakeLanguageModel())
"""


@pytest.fixture
def run_in_other_process(project: dict[str, Path], tmp_path: Path) -> Iterator[subprocess.Popen]:
    """Ein Lauf in einem anderen Prozess, der gerade sucht, solange der Test läuft.

    `project` legt vorher config.toml und profile.md in seinem Arbeitsordner an.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_REPO / "src"), str(_REPO)])
    process = subprocess.Popen(
        [sys.executable, "-c", _WAITING_RUN],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline() == "sucht\n"
        yield process
    finally:
        if process.poll() is None:
            process.communicate("absturz\n", timeout=60)


def test_cli_aborts_second_run_while_another_runs(
    run_in_other_process: subprocess.Popen,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_builtins: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = FakeSource()
    monkeypatch.setattr(main, "default_sources", lambda config, search_window: [source])

    exit_code = main.cli([])

    assert exit_code == 1
    assert capsys.readouterr().err == (
        "Fehler: Es läuft schon ein anderer Lauf (Sperrdatei jobagent.db.runlock); dieser "
        "bricht ab. Starte ihn erneut, wenn der andere fertig ist.\n"
    )
    assert source.received == []  # nichts gesucht, also auch nichts bewertet
    assert list((tmp_path / "output").glob("*.md")) == []  # kein Report


def test_cli_runs_after_other_run_was_killed(
    run_in_other_process: subprocess.Popen,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_today: Callable[[date], None],
    no_builtins: None,
) -> None:
    fixed_today(TODAY)
    monkeypatch.setattr(main, "default_sources", lambda config, search_window: [FakeSource()])
    run_in_other_process.communicate("absturz\n", timeout=60)  # hart, ohne aufzuräumen
    assert run_in_other_process.returncode == 1

    assert main.cli([]) == 0
    assert (tmp_path / "output" / "2026-03-02.md").exists()


def test_cli_runs_after_other_run_finished(
    run_in_other_process: subprocess.Popen,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_today: Callable[[date], None],
    no_builtins: None,
) -> None:
    fixed_today(TODAY)
    monkeypatch.setattr(main, "default_sources", lambda config, search_window: [FakeSource()])
    run_in_other_process.communicate("weiter\n", timeout=60)
    assert run_in_other_process.returncode == 0

    assert main.cli([]) == 0


def test_feedback_profile_suggestion_and_demo_work_while_a_run_runs(
    run_in_other_process: subprocess.Popen,
    project: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = project["db_path"]

    assert feedback.main(["beworben", "--firma", "Firma X", "--titel", "Dev"], db_path=db_path) == 0
    assert (
        profile_suggestion.main(
            db_path=db_path,
            profile_path=project["profile_path"],
            language_model=FakeLanguageModel(),
            ask=lambda question: "n",
        )
        == 0
    )
    assert main.demo_run().startswith("# Stellenvorschläge")


def test_arbeitnow_from_default_sources_skips_job_ads_older_than_search_window() -> None:
    # Arbeitnow liest die echte Uhr; die Zeitstempel liegen daher weit davor und danach.
    year_3000, year_1970 = 32503680000, 86400
    entries = [_arbeitnow_entry("neu", year_3000), _arbeitnow_entry("alt", year_1970)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": entries})

    config = Config(keywords=["Python"])  # ohne veroeffentlichtseit: nur der Suchzeitraum zählt
    window = SearchWindow(2, since=date(2026, 3, 1), capped=False)
    [_, arbeitnow] = main.default_sources(config, window, transport=httpx.MockTransport(handler))

    assert [job_ad.id for job_ad in arbeitnow.search(["Python"]).job_ads] == ["arbeitnow:neu"]


def _arbeitnow_entry(slug: str, created_at: float) -> dict:
    return {
        "slug": slug,
        "title": "Python Developer",
        "url": f"https://example.com/{slug}",
        "created_at": created_at,
    }


def _search_windows_of_main(monkeypatch: pytest.MonkeyPatch) -> list[SearchWindow]:
    """Lässt main mit einer leeren Fake-Quelle laufen und hält die Suchzeiträume fest."""
    windows: list[SearchWindow] = []

    def sources(config: Config, search_window: SearchWindow) -> list[FakeSource]:
        windows.append(search_window)
        return [FakeSource()]

    monkeypatch.setattr(main, "default_sources", sources)
    return windows


def test_main_searches_since_last_complete_run(
    project: dict[str, Path],
    fixed_today: Callable[[date], None],
    monkeypatch: pytest.MonkeyPatch,
    no_builtins: None,
) -> None:
    windows = _search_windows_of_main(monkeypatch)
    model = FakeLanguageModel(assessment_answer())
    monday, thursday = date(2026, 11, 16), date(2026, 11, 19)

    fixed_today(monday)
    # sources=None: die eingebauten, hier ersetzt durch _search_windows_of_main
    main.main(**project, sources=None, language_model=model)
    fixed_today(thursday)
    path = main.main(**project, sources=None, language_model=model)

    # In _CONFIG steht veroeffentlichtseit = 1: Startwert, danach Höchstwert.
    assert windows == [
        SearchWindow(1, since=None, capped=False),
        SearchWindow(1, since=monday, capped=True),
    ]
    assert "Suchzeitraum: 1 Tag (seit dem vollständigen Lauf vom 16.11., auf 1 Tag begrenzt)" in (
        path.read_text(encoding="utf-8")
    )


def test_main_counts_from_last_complete_run_after_failed_source(
    project: dict[str, Path],
    fixed_today: Callable[[date], None],
    no_builtins: None,
) -> None:
    project["config_path"].write_text(
        _CONFIG.replace("veroeffentlichtseit = 1", "veroeffentlichtseit = 7"), encoding="utf-8"
    )
    model = FakeLanguageModel(assessment_answer())

    fixed_today(date(2026, 11, 16))
    main.main(**project, sources=[FakeSource()], language_model=model)
    fixed_today(date(2026, 11, 18))
    main.main(**project, sources=[FakeSource(errors=["Data: Timeout"])], language_model=model)
    fixed_today(date(2026, 11, 19))
    path = main.main(**project, sources=[FakeSource()], language_model=model)

    assert "Suchzeitraum: 4 Tage (seit dem vollständigen Lauf vom 16.11.)" in path.read_text(
        encoding="utf-8"
    )
