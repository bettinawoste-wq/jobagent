"""Tests für main.py: Zusammenbau des Laufs und die eingebauten Quellen.

Das Verhalten des Laufs selbst prüft `tests/test_run.py`. Hier geht ein ganzer Lauf über den
Zusammenbau: Konfiguration und Suchprofil aus Dateien, Fake-Quellen und `FakeLanguageModel`,
aber echtes SQLite und eine echte Report-Datei.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx
import pytest

from jobagent import main
from jobagent.config import Config
from jobagent.job_ad import JobAd
from jobagent.language_model import AnthropicLanguageModel
from jobagent.score import Assessment
from jobagent.sources import SearchResult
from jobagent.sources.watchlist import WatchlistCompany
from jobagent.store import Store
from tests.fakes import FakeLanguageModel

TODAY = date(2026, 3, 2)

_CONFIG = """
wo = "München"
umkreis = 30
veroeffentlichtseit = 1
was = ["Softwareentwickler", "Data"]
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
