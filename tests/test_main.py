"""Tests fuer main.py: Ablauf suchen -> dedupe -> score -> report, mit Fake-Quellen."""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from jobagent import feedback, main, score, store
from jobagent.config import Config
from jobagent.job_ad import JobAd
from jobagent.score import Assessment
from jobagent.sources import SearchResult
from jobagent.sources.watchlist import WatchlistCompany

_CONFIG = """
wo = "München"
umkreis = 30
veroeffentlichtseit = 1
was = ["Softwareentwickler"]
"""

_PROFILE = "# Suchprofil\nPython, München, Hybrid bevorzugt."


@dataclass
class FakeSource:
    """Quelle am Interface `Source`, die feste Anzeigen und Fehler liefert."""

    job_ads: list[JobAd] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    name: str = "Bundesagentur für Arbeit"
    received: list[list[str]] = field(default_factory=list)

    def search(self, keywords: list[str]) -> SearchResult:
        self.received.append(keywords)
        return SearchResult(list(self.job_ads), list(self.errors))


class BrokenSource:
    name = "Bundesagentur für Arbeit"

    def search(self, keywords: list[str]) -> SearchResult:
        raise KeyError("referenznummer")


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


def _run(project: dict[str, Path], *sources) -> Path:
    return main.main(**project, sources=list(sources))


def _job_ad(id_: str) -> JobAd:
    return JobAd(
        id=id_,
        title=f"Stelle {id_}",
        company="Beispiel GmbH",
        location="München",
        link=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{id_}",
    )


def _assessment() -> Assessment:
    return Assessment(score=4, fits=["Python"], misfits=[], gaps=[], summary="Passt.")


def _score_and_record(calls: list[str]):
    def score_job_ad(job_ad: JobAd, profile: str) -> Assessment:
        calls.append(job_ad.id)
        return _assessment()

    return score_job_ad


def test_main_writes_report_for_new_matches(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    path = _run(project, FakeSource([_job_ad("a-1")]))

    content = path.read_text(encoding="utf-8")
    assert "Stelle a-1" in content
    assert "4/5" in content


def test_main_passes_all_keywords_to_each_source_at_once(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project["config_path"].write_text('was = ["A", "B"]\n', encoding="utf-8")
    first, second = FakeSource(), FakeSource(name="Arbeitnow")

    _run(project, first, second)

    assert first.received == [["A", "B"]]
    assert second.received == [["A", "B"]]


def test_main_writes_source_status_into_report(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    content = _run(
        project,
        FakeSource([_job_ad("a-1")]),
        FakeSource([], ["x: HTTP 500"], name="Arbeitnow"),
    ).read_text(encoding="utf-8")

    assert "- Bundesagentur für Arbeit: 1 Anzeige\n" in content
    assert "- Arbeitnow: FEHLER, 0 Anzeigen (x: HTTP 500)" in content
    assert "Firmen-Watchlist" not in content


def test_main_counts_job_ads_once_and_merges_same_errors(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())
    source = FakeSource([_job_ad("a-1"), _job_ad("a-1")], ["kaputt", "kaputt"])

    content = _run(project, source).read_text(encoding="utf-8")

    assert "- Bundesagentur für Arbeit: FEHLER, 1 Anzeige (kaputt)\n" in content


def test_main_survives_unexpected_source_error(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    content = _run(
        project, BrokenSource(), FakeSource([_job_ad("a-1")], name="Arbeitnow")
    ).read_text(encoding="utf-8")

    assert "- Bundesagentur für Arbeit: FEHLER, 0 Anzeigen (unerwarteter Fehler)" in content
    assert "Stelle a-1" in content


def test_main_takes_min_score_from_config(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project["config_path"].write_text('was = ["A"]\nmindest_score = 5\n', encoding="utf-8")
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    content = _run(project, FakeSource([_job_ad("a-1")])).read_text(encoding="utf-8")

    assert "## Weitere Treffer (Score unter 5)" in content
    assert "- **1.** Stelle a-1" in content


def test_main_uses_default_min_score_without_config(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: replace(_assessment(), score=2))

    content = _run(project, FakeSource([_job_ad("a-1")])).read_text(encoding="utf-8")

    assert "## Weitere Treffer (Score unter 3)" in content


def test_main_remembers_report_and_match_number(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    scores = {"a-1": 2, "a-2": 5}

    def assess(job_ad: JobAd, profile: str) -> Assessment:
        return replace(_assessment(), score=scores[job_ad.id])

    monkeypatch.setattr(score, "score_job_ad", assess)

    path = _run(project, FakeSource([_job_ad("a-1"), _job_ad("a-2")]))

    conn = store.connect(project["db_path"])
    try:
        rows = conn.execute(
            "SELECT id, report, nummer FROM gesehene_anzeigen ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("a-1", path.stem, 2), ("a-2", path.stem, 1)]


def test_main_skips_already_seen_job_ads(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr(score, "score_job_ad", _score_and_record(calls))
    source = FakeSource([_job_ad("a-1")])

    _run(project, source)
    second_run_path = _run(project, source)

    assert calls == ["a-1"]
    assert "Keine neuen Treffer" in second_run_path.read_text(encoding="utf-8")


def test_main_without_search_results_writes_note(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())

    path = _run(project, FakeSource())

    assert "Keine neuen Treffer" in path.read_text(encoding="utf-8")


def test_main_does_not_mark_seen_when_assessment_fails(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = FakeSource([_job_ad("a-1")])
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: None)

    first_run = _run(project, source)
    assert "Keine neuen Treffer" in first_run.read_text(encoding="utf-8")

    calls = []
    monkeypatch.setattr(score, "score_job_ad", _score_and_record(calls))
    second_run = _run(project, source)

    assert calls == ["a-1"]
    assert "Stelle a-1" in second_run.read_text(encoding="utf-8")


def test_main_deduplicates_matches_across_sources(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr(score, "score_job_ad", _score_and_record(calls))

    content = _run(
        project,
        FakeSource([_job_ad("a-1")]),
        FakeSource([_job_ad("a-1")], name="Arbeitnow"),
    ).read_text(encoding="utf-8")

    assert calls == ["a-1"]
    assert "- Bundesagentur für Arbeit: 1 Anzeige\n" in content
    assert "- Arbeitnow: 1 Anzeige\n" in content


def test_main_combines_matches_from_both_sources(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    arbeitnow_job_ad = JobAd(
        id="arbeitnow:full-stack-entwickler-100",
        title="Full-Stack-Entwickler (m/w/d)",
        company="Arbeitnow-Firma",
        location="Berlin",
        link="https://www.arbeitnow.com/jobs/companies/arbeitnow-firma/full-stack-entwickler-100",
    )
    calls = []
    monkeypatch.setattr(score, "score_job_ad", _score_and_record(calls))

    path = _run(
        project,
        FakeSource([_job_ad("a-1")]),
        FakeSource([arbeitnow_job_ad], name="Arbeitnow"),
    )

    content = path.read_text(encoding="utf-8")
    assert "Stelle a-1" in content
    assert "Full-Stack-Entwickler (m/w/d)" in content
    assert sorted(calls) == ["a-1", "arbeitnow:full-stack-entwickler-100"]


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


def _position_job_ad(
    id_: str, description: str | None = "Text", title: str = "Data Engineer"
) -> JobAd:
    return JobAd(
        id=id_,
        title=title,
        company="Beispiel GmbH",
        location="München",
        link=f"https://x.example/{id_}",
        description=description,
    )


def _run_finds(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch, job_ad: JobAd
) -> tuple[Path, str]:
    monkeypatch.setattr(score, "score_job_ad", lambda *a, **kw: _assessment())
    path = _run(project, FakeSource([job_ad]))
    return path, path.read_text(encoding="utf-8")


def _manual(project: dict[str, Path], action: str = "beworben", title: str = "Data Engineer"):
    argv = [action, "--firma", "Beispiel", "--titel", title]
    assert feedback.main(argv, db_path=project["db_path"]) == 0


def _application_to_first_job_ad(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch, description: str | None
) -> None:
    path, _ = _run_finds(project, monkeypatch, _position_job_ad("alt", description))
    assert feedback.main([path.stem, "1", "beworben"], db_path=project["db_path"]) == 0


def test_main_moves_applied_position_to_own_block(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manual(project)

    _, content = _run_finds(project, monkeypatch, _position_job_ad("neu"))

    assert "## Bereits beworben" in content
    assert "Data Engineer (Beispiel GmbH, München) – Score 4/5 – beworben, beworben am" in content
    assert "## 1. Data Engineer" not in content


def test_main_detects_position_despite_company_name_in_title(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manual(project)
    job_ad = _position_job_ad("neu", title="Beispiel GmbH: Data Engineer (w/m/x)")

    _, content = _run_finds(project, monkeypatch, job_ad)

    assert "## Bereits beworben" in content


def test_main_shows_application_status(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manual(project)
    _manual(project, "absage")

    _, content = _run_finds(project, monkeypatch, _position_job_ad("neu"))

    assert "– absage, beworben am" in content


def test_main_withdrawn_application_does_not_count(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manual(project)
    _manual(project, "zurückgezogen")

    _, content = _run_finds(project, monkeypatch, _position_job_ad("neu"))

    assert "Bereits beworben" not in content
    assert "## 1. Data Engineer" in content


def test_main_other_position_stays_unmarked(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manual(project, title="Consultant")

    _, content = _run_finds(project, monkeypatch, _position_job_ad("neu"))

    assert "Bereits beworben" not in content


def test_main_job_ad_without_company_is_not_matched(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["beworben", "--firma", "", "--titel", "Data Engineer"]
    feedback.main(argv, db_path=project["db_path"])
    without_company = replace(_position_job_ad("neu"), company=None)

    _, content = _run_finds(project, monkeypatch, without_company)

    assert "Bereits beworben" not in content


def test_main_reports_identical_text(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _application_to_first_job_ad(project, monkeypatch, "Gleicher Text")

    _, content = _run_finds(project, monkeypatch, _position_job_ad("neu", "Gleicher   Text"))

    assert "– Text identisch –" in content


def test_main_reports_text_differs(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _application_to_first_job_ad(project, monkeypatch, "Alter Text")

    _, content = _run_finds(project, monkeypatch, _position_job_ad("neu", "Neuer Text"))

    assert "– Text weicht von deiner Bewerbung ab –" in content


def test_main_manual_application_is_not_comparable(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manual(project)

    _, content = _run_finds(project, monkeypatch, _position_job_ad("neu"))

    assert "– Text nicht vergleichbar –" in content


def test_main_missing_new_description_is_not_comparable(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _application_to_first_job_ad(project, monkeypatch, "Alter Text")

    _, content = _run_finds(project, monkeypatch, _position_job_ad("neu", None))

    assert "– Text nicht vergleichbar –" in content


def test_main_compares_with_latest_application(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _application_to_first_job_ad(project, monkeypatch, "Erster Text")
    path, _ = _run_finds(project, monkeypatch, _position_job_ad("zwei", "Zweiter Text"))
    assert feedback.main([path.stem, "1", "beworben"], db_path=project["db_path"]) == 0

    _, content = _run_finds(project, monkeypatch, _position_job_ad("drei", "Zweiter Text"))

    assert "– Text identisch –" in content


def _applied_days_ago(project: dict[str, Path], days: int, status: str = "beworben") -> None:
    applied_on = (date.today() - timedelta(days=days)).isoformat()
    base = ["--firma", "Firma X", "--titel", "Dev"]
    assert feedback.main(["beworben", *base, "--am", applied_on], db_path=project["db_path"]) == 0
    if status != "beworben":
        assert feedback.main([status, *base], db_path=project["db_path"]) == 0


def _run_without_matches(project: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> str:
    return _run(project, FakeSource()).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("days", "expected"), [(13, False), (14, True), (20, True), (28, True), (29, False)]
)
def test_main_follow_up_window(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch, days: int, expected: bool
) -> None:
    _applied_days_ago(project, days)

    content = _run_without_matches(project, monkeypatch)

    assert ("## Nachfassen" in content) is expected
    if expected:
        assert f"seit {days} Tagen keine Antwort" in content


@pytest.mark.parametrize("status", ["gespräch", "absage", "zusage", "zurückgezogen"])
def test_main_follow_up_only_for_status_applied(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    _applied_days_ago(project, 20, status)

    assert "Nachfassen" not in _run_without_matches(project, monkeypatch)


def test_main_follow_up_days_from_config(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project["config_path"].write_text(
        'was = ["A"]\nnachfassen_ab_tag = 3\nnachfassen_bis_tag = 5\n', encoding="utf-8"
    )
    _applied_days_ago(project, 4)

    assert "seit 4 Tagen keine Antwort" in _run_without_matches(project, monkeypatch)


def test_main_follow_up_reminder_does_not_change_status(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _applied_days_ago(project, 60)

    _run_without_matches(project, monkeypatch)

    conn = store.connect(project["db_path"])
    try:
        assert conn.execute("SELECT status FROM bewerbungen").fetchall() == [("beworben",)]
    finally:
        conn.close()


def _open_feedback(project: dict[str, Path], count: int) -> None:
    conn = store.connect(project["db_path"])
    for number in range(count):
        job_ad_id = f"f-{number}"
        store.mark_seen(conn, _job_ad(job_ad_id), _assessment(), date.today())
        store.save_feedback(conn, job_ad_id, 3, None, date.today())
    conn.close()


@pytest.mark.parametrize(("count", "expected"), [(4, False), (5, True), (7, True)])
def test_main_profile_suggestion_hint_from_five_feedbacks(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch, count: int, expected: bool
) -> None:
    _open_feedback(project, count)

    content = _run_without_matches(project, monkeypatch)

    assert ("## Profil-Vorschlag" in content) is expected
    if expected:
        assert f"- {count} Rückmeldungen warten" in content


def test_main_processed_feedback_does_not_count(
    project: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _open_feedback(project, 5)
    conn = store.connect(project["db_path"])
    store.mark_feedback_processed(conn, ["f-0"])
    conn.close()

    assert "Profil-Vorschlag" not in _run_without_matches(project, monkeypatch)


def test_run_with_own_sources_assessment_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*args, **kwargs):
        raise AssertionError("Eingebaute Quelle darf nicht aufgerufen werden")

    def no_model(*args, **kwargs):
        raise AssertionError("Haiku-Bewertung darf nicht aufgerufen werden")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(score, "score_job_ad", no_model)
    scores = {"a-1": 3, "a-2": 5, "b-1": 4}
    assessed: list[str] = []

    def assess(job_ad: JobAd) -> Assessment:
        assessed.append(job_ad.id)
        return replace(_assessment(), score=scores[job_ad.id])

    path = main.main(
        config_path=tmp_path / "fehlt.toml",
        profile_path=tmp_path / "fehlt.md",
        db_path=tmp_path / "jobagent.db",
        output_dir=tmp_path / "output",
        config=Config(keywords=["Python"]),
        sources=[
            FakeSource([_job_ad("a-1"), _job_ad("a-2")], name="Quelle A"),
            FakeSource([_job_ad("b-1")], ["Python: HTTP 503"], name="Quelle B"),
        ],
        assess=assess,
    )

    content = path.read_text(encoding="utf-8")
    assert sorted(assessed) == ["a-1", "a-2", "b-1"]
    assert "- Quelle A: 2 Anzeigen\n" in content
    assert "- Quelle B: FEHLER, 1 Anzeige (Python: HTTP 503)\n" in content
    assert "Bundesagentur" not in content
    assert (
        content.index("## 1. Stelle a-2")
        < content.index("## 2. Stelle b-1")
        < content.index("## 3. Stelle a-1")
    )
