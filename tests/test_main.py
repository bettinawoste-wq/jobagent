"""Tests für main.py: Zusammenbau des Laufs und die eingebauten Quellen.

Das Verhalten des Laufs selbst prüft `tests/test_run.py`. Hier geht ein ganzer Lauf über den
Zusammenbau: Konfiguration und Suchprofil aus Dateien, Fake-Quellen und `FakeLanguageModel`,
aber echtes SQLite und eine echte Report-Datei.
"""

import dataclasses
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx
import pytest

from jobagent import main
from jobagent.config import Config
from jobagent.job_ad import JobAd
from jobagent.language_model import AnthropicLanguageModel, LanguageModelError
from jobagent.score import Assessment
from jobagent.sources import SearchResult
from jobagent.sources.watchlist import WatchlistCompany
from jobagent.store import Store
from tests.fakes import FakeLanguageModel

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


@dataclass
class FakeSource:
    """Quelle am Interface `Source`, die feste Anzeigen liefert und Suchbegriffe festhält."""

    job_ads: list[JobAd] = field(default_factory=list)
    name: str = "Quelle A"
    received: list[list[str]] = field(default_factory=list)

    def search(self, keywords: list[str]) -> SearchResult:
        self.received.append(keywords)
        return SearchResult(list(self.job_ads), [])


def _job_ad(id_: str) -> JobAd:
    return JobAd(
        id=id_,
        title=f"Stelle {id_}",
        company="Beispiel GmbH",
        location="München",
        link=f"https://example.com/{id_}",
    )


def _answer(score: int) -> dict:
    return Assessment(score, ["Python"], [], [], "Passt.").as_model_answer()


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
    source = FakeSource([_job_ad("a-1"), _job_ad("a-2")])
    model = FakeLanguageModel(_answer(4), _answer(5))

    path = main.main(**project, sources=[source], language_model=model)

    assert path == project["output_dir"] / "2026-03-02.md"
    content = path.read_text(encoding="utf-8")
    assert "- Quelle A: 2 Anzeigen\n" in content
    assert content.index("## 1. Stelle a-2") < content.index("## Weitere Treffer (Score unter 5)")
    assert "- **2.** Stelle a-1" in content
    assert source.received == [["Softwareentwickler", "Data"]]
    assert all(_PROFILE in request.text for request in model.requests)
    with Store(project["db_path"]) as db:
        assert db.find_match("2026-03-02", 1).id == "a-2"
        assert not db.is_new("a-1")


def test_main_reads_search_profile_with_bom_without_the_bom(
    project: dict[str, Path], fixed_today: Callable[[date], None], no_builtins: None
) -> None:
    fixed_today(TODAY)
    project["profile_path"].write_text(_PROFILE, encoding="utf-8-sig")
    model = FakeLanguageModel(_answer(4))

    main.main(**project, sources=[FakeSource([_job_ad("a-1")])], language_model=model)

    assert chr(0xFEFF) not in model.requests[0].text  # kein BOM
    assert _PROFILE in model.requests[0].text


def test_main_keeps_seen_job_ads_in_database_between_runs(
    project: dict[str, Path], fixed_today: Callable[[date], None], no_builtins: None
) -> None:
    fixed_today(TODAY)
    source = FakeSource([_job_ad("a-1")])
    model = FakeLanguageModel(_answer(4))

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


def _output_is_file(folder: Path) -> None:
    (folder / "output").write_text("kein Ordner", encoding="utf-8")


@pytest.mark.parametrize(
    ("breakage", "message"),
    [
        (_broken_toml, "Fehler: config.toml ist kein gültiges TOML"),
        (_misplaced_key, "Fehler: config.toml ist nicht richtig gegliedert"),
        (_no_config, "Fehler: config.toml nicht gefunden"),
        (_no_profile, "Fehler: Suchprofil profile.md nicht gefunden"),
        (_database_is_folder, "Fehler: Datenbank jobagent.db nicht nutzbar"),
        (_output_is_file, "Fehler: Report lässt sich nicht in output schreiben"),
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
    monkeypatch.setattr(main, "default_sources", lambda config: [FakeSource()])
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
    monkeypatch.setattr(main, "default_sources", lambda config: [FakeSource()])

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
    source = FakeSource([_job_ad("a-1")])
    monkeypatch.setattr(main, "default_sources", lambda config: [source])
    model = FakeLanguageModel(LanguageModelError("Zeitüberschreitung"))
    monkeypatch.setattr(main, "AnthropicLanguageModel", lambda model_name: model)

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
    names = [source.name for source in main.default_sources(Config())]

    assert names == ["Bundesagentur für Arbeit", "Arbeitnow"]


def test_default_sources_include_watchlist_with_companies_from_config() -> None:
    config = Config(companies=[WatchlistCompany(name="GitLab", ats="greenhouse", slug="gitlab")])

    names = [source.name for source in main.default_sources(config)]

    assert names == ["Bundesagentur für Arbeit", "Arbeitnow", "Firmen-Watchlist"]


def test_default_sources_search_with_location_radius_and_age_from_config() -> None:
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

    for source in main.default_sources(config, transport=httpx.MockTransport(handler)):
        assert source.search(config.keywords).errors == []

    hosts = [request.url.host for request in requests]
    assert hosts == ["rest.arbeitsagentur.de", "www.arbeitnow.com", "boards-api.greenhouse.io"]
    assert dict(requests[0].url.params) == {
        "was": "Python",
        "wo": "München",
        "umkreis": "30",
        "veroeffentlichtseit": "7",
    }


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


def test_cli_logs_job_ad_ids_but_never_their_full_text(
    project: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_today: Callable[[date], None],
    no_builtins: None,
) -> None:
    fixed_today(TODAY)
    full_text = "Wir suchen eine Entwicklerin mit Leidenschaft für saubere Daten."
    job_ad = JobAd("a-1", "Stelle a-1", "Beispiel GmbH", "München", "https://example.com/a-1")
    job_ad = dataclasses.replace(job_ad, description=full_text)
    monkeypatch.setattr(main, "default_sources", lambda config: [FakeSource([job_ad])])

    class ChattyLanguageModel(FakeLanguageModel):
        """Loggt wie das SDK von Anthropic die ganze Anfrage auf DEBUG und scheitert dann."""

        def ask(self, system: str, text: str, schema: dict) -> dict:
            logging.getLogger("anthropic._base_client").debug("Request options: %s", text)
            return super().ask(system, text, schema)

    model = ChattyLanguageModel(LanguageModelError(f"Antwort zu: {job_ad.id}"))
    monkeypatch.setattr(main, "AnthropicLanguageModel", lambda model_name: model)

    main.cli([])

    assert full_text in model.requests[0].text  # das Sprachmodell hat den Volltext bekommen
    log = (tmp_path / "output" / "2026-03-02.log").read_text(encoding="utf-8")
    assert "anzeige='a-1'" in log
    assert "Leidenschaft" not in log
