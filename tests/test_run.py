"""Tests für den Lauf `run`: suchen, deduplizieren, bewerten, Report schreiben.

Der Lauf bekommt alles übergeben; die Tests geben ihm Fake-Quellen, `FakeLanguageModel`,
einen `Store` auf echtem SQLite, eine `Config`, ein festes Datum und einen Report-Ordner.
"""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from jobagent.config import Config
from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModelError
from jobagent.position import position_key
from jobagent.run import run
from jobagent.score import Assessment
from jobagent.sources import SearchResult, Source
from jobagent.store import ApplicationStatus, NewApplication, Store
from tests.fakes import FakeLanguageModel

TODAY = date(2026, 3, 2)

_CONFIG = Config(keywords=["Softwareentwickler"])

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


@pytest.fixture
def db(tmp_path: Path):
    with Store(tmp_path / "jobagent.db") as db:
        yield db


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "output"


def _run(
    db: Store,
    output_dir: Path,
    *sources: Source,
    model: FakeLanguageModel | None = None,
    config: Config = _CONFIG,
    today: date = TODAY,
) -> str:
    """Lauf mit Fake-Quellen; ohne `model` bewertet ein Sprachmodell jede Anzeige mit 4.

    Liefert den Text des geschriebenen Reports.
    """
    path = run(
        sources=list(sources),
        language_model=model or FakeLanguageModel(_answer()),
        search_profile=_PROFILE,
        store=db,
        config=config,
        today=today,
        output_dir=output_dir,
    )
    return path.read_text(encoding="utf-8")


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


def _answer(score: int = 4) -> dict:
    """Antwort des Sprachmodells auf eine Bewertung, unter den deutschen Schlüsseln."""
    return replace(_assessment(), score=score).as_model_answer()


def test_run_writes_report_for_new_matches(db: Store, output_dir: Path) -> None:
    content = _run(db, output_dir, FakeSource([_job_ad("a-1")]))

    assert "Stelle a-1" in content
    assert "4/5" in content


def _asked_about(model: FakeLanguageModel) -> list[str]:
    """Die Titel der Anzeigen, nach denen der Lauf das Sprachmodell gefragt hat."""
    return [
        line.removeprefix("Titel: ")
        for request in model.requests
        for line in request.text.splitlines()
        if line.startswith("Titel: ")
    ]


class BrokenSource:
    name = "Bundesagentur für Arbeit"

    def search(self, keywords: list[str]) -> SearchResult:
        raise KeyError("referenznummer")


def test_run_assesses_against_given_profile(db: Store, output_dir: Path) -> None:
    model = FakeLanguageModel(_answer())

    _run(db, output_dir, FakeSource([_job_ad("a-1")]), model=model)

    assert _PROFILE in model.requests[0].system + model.requests[0].text


def test_run_writes_report_dated_today_into_output_dir(db: Store, output_dir: Path) -> None:
    path = run(
        sources=[FakeSource([_job_ad("a-1")])],
        language_model=FakeLanguageModel(_answer()),
        search_profile=_PROFILE,
        store=db,
        config=_CONFIG,
        today=TODAY,
        output_dir=output_dir,
    )

    assert path == output_dir / "2026-03-02.md"


def test_run_passes_all_keywords_to_each_source_at_once(db: Store, output_dir: Path) -> None:
    first, second = FakeSource(), FakeSource(name="Arbeitnow")

    _run(db, output_dir, first, second, config=Config(keywords=["A", "B"]))

    assert first.received == [["A", "B"]]
    assert second.received == [["A", "B"]]


def test_run_writes_source_status_into_report(db: Store, output_dir: Path) -> None:
    content = _run(
        db,
        output_dir,
        FakeSource([_job_ad("a-1")]),
        FakeSource([], ["x: HTTP 500"], name="Arbeitnow"),
    )

    assert "- Bundesagentur für Arbeit: 1 Anzeige\n" in content
    assert "- Arbeitnow: FEHLER, 0 Anzeigen (x: HTTP 500)" in content
    assert "Firmen-Watchlist" not in content


def test_run_counts_job_ads_once_and_merges_same_errors(db: Store, output_dir: Path) -> None:
    source = FakeSource([_job_ad("a-1"), _job_ad("a-1")], ["kaputt", "kaputt"])

    content = _run(db, output_dir, source)

    assert "- Bundesagentur für Arbeit: FEHLER, 1 Anzeige (kaputt)\n" in content


def test_run_survives_unexpected_source_error(db: Store, output_dir: Path) -> None:
    content = _run(
        db,
        output_dir,
        BrokenSource(),
        FakeSource([_job_ad("a-1")], name="Arbeitnow"),
        config=Config(keywords=["Python", "Data"]),
    )

    assert (
        "- Bundesagentur für Arbeit: FEHLER, 0 Anzeigen (Python, Data: unerwarteter Fehler)"
        in content
    )
    assert "Stelle a-1" in content


def test_run_takes_min_score_from_config(db: Store, output_dir: Path) -> None:
    config = Config(keywords=["A"], min_score=5)

    content = _run(db, output_dir, FakeSource([_job_ad("a-1")]), config=config)

    assert "## Weitere Treffer (Score unter 5)" in content
    assert "- **1.** Stelle a-1" in content


def test_run_remembers_report_and_match_number(db: Store, output_dir: Path) -> None:
    model = FakeLanguageModel(_answer(score=2), _answer(score=5))

    _run(db, output_dir, FakeSource([_job_ad("a-1"), _job_ad("a-2")]), model=model)

    assert db.find_match("2026-03-02", 1).id == "a-2"
    assert db.find_match("2026-03-02", 2).id == "a-1"


def test_run_skips_already_seen_job_ads(db: Store, output_dir: Path) -> None:
    model = FakeLanguageModel(_answer())
    source = FakeSource([_job_ad("a-1")])

    _run(db, output_dir, source, model=model)
    second_run = _run(db, output_dir, source, model=model)

    assert _asked_about(model) == ["Stelle a-1"]
    assert "Keine neuen Treffer" in second_run


def test_run_without_search_results_writes_note(db: Store, output_dir: Path) -> None:
    assert "Keine neuen Treffer" in _run(db, output_dir, FakeSource())


def test_run_does_not_mark_seen_when_assessment_fails(db: Store, output_dir: Path) -> None:
    source = FakeSource([_job_ad("a-1")])

    first_run = _run(db, output_dir, source, model=FakeLanguageModel(LanguageModelError("weg")))
    assert "Keine neuen Treffer" in first_run

    model = FakeLanguageModel(_answer())
    second_run = _run(db, output_dir, source, model=model)

    assert _asked_about(model) == ["Stelle a-1"]
    assert "Stelle a-1" in second_run


def test_run_does_not_mark_seen_when_answer_is_invalid(db: Store, output_dir: Path) -> None:
    source = FakeSource([_job_ad("a-1")])

    first_run = _run(db, output_dir, source, model=FakeLanguageModel(_answer(score=7)))
    assert "Keine neuen Treffer" in first_run

    assert "Stelle a-1" in _run(db, output_dir, source)


def test_run_deduplicates_matches_across_sources(db: Store, output_dir: Path) -> None:
    model = FakeLanguageModel(_answer())

    content = _run(
        db,
        output_dir,
        FakeSource([_job_ad("a-1")]),
        FakeSource([_job_ad("a-1")], name="Arbeitnow"),
        model=model,
    )

    assert _asked_about(model) == ["Stelle a-1"]
    assert "- Bundesagentur für Arbeit: 1 Anzeige\n" in content
    assert "- Arbeitnow: 1 Anzeige\n" in content


def test_run_combines_matches_from_both_sources(db: Store, output_dir: Path) -> None:
    arbeitnow_job_ad = JobAd(
        id="arbeitnow:full-stack-entwickler-100",
        title="Full-Stack-Entwickler (m/w/d)",
        company="Arbeitnow-Firma",
        location="Berlin",
        link="https://www.arbeitnow.com/jobs/companies/arbeitnow-firma/full-stack-entwickler-100",
    )
    model = FakeLanguageModel(_answer())

    content = _run(
        db,
        output_dir,
        FakeSource([_job_ad("a-1")]),
        FakeSource([arbeitnow_job_ad], name="Arbeitnow"),
        model=model,
    )

    assert "Stelle a-1" in content
    assert "Full-Stack-Entwickler (m/w/d)" in content
    assert sorted(_asked_about(model)) == ["Full-Stack-Entwickler (m/w/d)", "Stelle a-1"]


def test_run_sorts_matches_by_score(db: Store, output_dir: Path) -> None:
    model = FakeLanguageModel(_answer(3), _answer(5), _answer(4))

    content = _run(
        db,
        output_dir,
        FakeSource([_job_ad("a-1"), _job_ad("a-2")], name="Quelle A"),
        FakeSource([_job_ad("b-1")], name="Quelle B"),
        model=model,
    )

    assert _asked_about(model) == ["Stelle a-1", "Stelle a-2", "Stelle b-1"]
    assert (
        content.index("## 1. Stelle a-2")
        < content.index("## 2. Stelle b-1")
        < content.index("## 3. Stelle a-1")
    )


# Bewerbungen: Der Lauf erkennt eine Stelle wieder, auf die schon eine Bewerbung läuft.


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


def _manual(
    db: Store,
    status: ApplicationStatus = ApplicationStatus.APPLIED,
    title: str = "Data Engineer",
    company: str = "Beispiel",
) -> None:
    """Bewerbung ohne Treffer, wie `beworben --firma ... --titel ...`, oder Statuswechsel."""
    key = position_key(company, title)
    application_id = db.latest_application(key)
    if application_id is None:
        application = NewApplication(key, company, title, None)
        db.create_application(application, ApplicationStatus.APPLIED, TODAY)
    else:
        db.update_application(application_id, status, None)


def _application_to(db: Store, output_dir: Path, job_ad: JobAd) -> None:
    """Ein Lauf findet `job_ad`, danach geht eine Bewerbung auf genau diesen Treffer."""
    _run(db, output_dir, FakeSource([job_ad]))
    key = position_key(job_ad.company, job_ad.title)
    application = NewApplication(key, job_ad.company, job_ad.title, job_ad.id)
    db.create_application(application, ApplicationStatus.APPLIED, TODAY)


def test_run_moves_applied_position_to_own_block(db: Store, output_dir: Path) -> None:
    _manual(db)

    content = _run(db, output_dir, FakeSource([_position_job_ad("neu")]))

    assert "## Bereits beworben" in content
    assert "Data Engineer (Beispiel GmbH, München) – Score 4/5 – beworben, beworben am" in content
    assert "## 1. Data Engineer" not in content


def test_run_detects_position_despite_company_name_in_title(db: Store, output_dir: Path) -> None:
    _manual(db)
    job_ad = _position_job_ad("neu", title="Beispiel GmbH: Data Engineer (w/m/x)")

    assert "## Bereits beworben" in _run(db, output_dir, FakeSource([job_ad]))


def test_run_shows_application_status(db: Store, output_dir: Path) -> None:
    _manual(db)
    _manual(db, ApplicationStatus.REJECTED)

    content = _run(db, output_dir, FakeSource([_position_job_ad("neu")]))

    assert "– absage, beworben am" in content


def test_run_withdrawn_application_does_not_count(db: Store, output_dir: Path) -> None:
    _manual(db)
    _manual(db, ApplicationStatus.WITHDRAWN)

    content = _run(db, output_dir, FakeSource([_position_job_ad("neu")]))

    assert "Bereits beworben" not in content
    assert "## 1. Data Engineer" in content


def test_run_other_position_stays_unmarked(db: Store, output_dir: Path) -> None:
    _manual(db, title="Consultant")

    content = _run(db, output_dir, FakeSource([_position_job_ad("neu")]))

    assert "Bereits beworben" not in content


def test_run_job_ad_without_company_is_not_matched(db: Store, output_dir: Path) -> None:
    _manual(db, company="")
    without_company = replace(_position_job_ad("neu"), company=None)

    content = _run(db, output_dir, FakeSource([without_company]))

    assert "Bereits beworben" not in content


def test_run_reports_identical_text(db: Store, output_dir: Path) -> None:
    _application_to(db, output_dir, _position_job_ad("alt", "Gleicher Text"))

    content = _run(db, output_dir, FakeSource([_position_job_ad("neu", "Gleicher   Text")]))

    assert "– Text identisch –" in content


def test_run_reports_text_differs(db: Store, output_dir: Path) -> None:
    _application_to(db, output_dir, _position_job_ad("alt", "Alter Text"))

    content = _run(db, output_dir, FakeSource([_position_job_ad("neu", "Neuer Text")]))

    assert "– Text weicht von deiner Bewerbung ab –" in content


def test_run_manual_application_is_not_comparable(db: Store, output_dir: Path) -> None:
    _manual(db)

    content = _run(db, output_dir, FakeSource([_position_job_ad("neu")]))

    assert "– Text nicht vergleichbar –" in content


def test_run_missing_new_description_is_not_comparable(db: Store, output_dir: Path) -> None:
    _application_to(db, output_dir, _position_job_ad("alt", "Alter Text"))

    content = _run(db, output_dir, FakeSource([_position_job_ad("neu", None)]))

    assert "– Text nicht vergleichbar –" in content


def test_run_compares_with_latest_application(db: Store, output_dir: Path) -> None:
    _application_to(db, output_dir, _position_job_ad("eins", "Erster Text"))
    _application_to(db, output_dir, _position_job_ad("zwei", "Zweiter Text"))

    content = _run(db, output_dir, FakeSource([_position_job_ad("drei", "Zweiter Text")]))

    assert "– Text identisch –" in content


# Nachfassen: Bewerbungen ohne Antwort im Fenster aus der Konfiguration.


def _applied_days_ago(
    db: Store, days: int, status: ApplicationStatus = ApplicationStatus.APPLIED
) -> None:
    application = NewApplication(position_key("Firma X", "Dev"), "Firma X", "Dev", None)
    db.create_application(application, ApplicationStatus.APPLIED, TODAY - timedelta(days=days))
    if status != ApplicationStatus.APPLIED:
        db.update_application(db.latest_application(application.position_key), status, None)


@pytest.mark.parametrize(
    ("days", "expected"), [(13, False), (14, True), (20, True), (28, True), (29, False)]
)
def test_run_follow_up_window(db: Store, output_dir: Path, days: int, expected: bool) -> None:
    _applied_days_ago(db, days)

    content = _run(db, output_dir, FakeSource())

    assert ("## Nachfassen" in content) is expected
    if expected:
        assert f"seit {days} Tagen keine Antwort" in content


@pytest.mark.parametrize(
    "status",
    [
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
        ApplicationStatus.OFFER,
        ApplicationStatus.WITHDRAWN,
    ],
)
def test_run_follow_up_only_for_status_applied(
    db: Store, output_dir: Path, status: ApplicationStatus
) -> None:
    _applied_days_ago(db, 20, status)

    assert "Nachfassen" not in _run(db, output_dir, FakeSource())


def test_run_follow_up_days_from_config(db: Store, output_dir: Path) -> None:
    config = Config(keywords=["A"], follow_up_min_days=3, follow_up_max_days=5)
    _applied_days_ago(db, 4)

    assert "seit 4 Tagen keine Antwort" in _run(db, output_dir, FakeSource(), config=config)


def test_run_follow_up_reminder_does_not_change_status(db: Store, output_dir: Path) -> None:
    _applied_days_ago(db, 20)

    _run(db, output_dir, FakeSource())

    application = db.current_application(position_key("Firma X", "Dev"))
    assert application.status == ApplicationStatus.APPLIED


# Profil-Vorschlag: Hinweis im Report, sobald genug Rückmeldungen offen sind.


def _open_feedback(db: Store, count: int) -> None:
    for number in range(count):
        job_ad_id = f"f-{number}"
        db.remember_job_ad(_job_ad(job_ad_id), _assessment(), TODAY)
        db.save_feedback(job_ad_id, 3, None, TODAY)


@pytest.mark.parametrize(("count", "expected"), [(4, False), (5, True), (7, True)])
def test_run_profile_suggestion_hint_from_five_feedbacks(
    db: Store, output_dir: Path, count: int, expected: bool
) -> None:
    _open_feedback(db, count)

    content = _run(db, output_dir, FakeSource())

    assert ("## Profil-Vorschlag" in content) is expected
    if expected:
        assert f"- {count} Rückmeldungen warten" in content


def test_run_processed_feedback_does_not_count(db: Store, output_dir: Path) -> None:
    _open_feedback(db, 5)
    db.mark_feedback_processed(["f-0"])

    assert "Profil-Vorschlag" not in _run(db, output_dir, FakeSource())
