"""Tests fuer report.py mit temporaerem Ausgabeverzeichnis."""

from datetime import date, timedelta
from pathlib import Path

from jobagent.fetch import Quellenstatus
from jobagent.job_ad import JobAd
from jobagent.report import AlreadyApplied, write_report
from jobagent.score import Assessment
from jobagent.store import FollowUpReminder


def _job_ad(id_: str, title: str) -> JobAd:
    return JobAd(
        id=id_,
        title=title,
        company="Beispiel GmbH",
        location="München",
        link=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{id_}",
    )


def _write_path(*args, **kwargs) -> Path:
    return write_report(*args, **kwargs).path


def _assessment(score: int, summary: str = "Passt gut.") -> Assessment:
    return Assessment(
        score=score,
        fits=["Python"],
        misfits=[],
        gaps=["Kubernetes"],
        summary=summary,
    )


def test_write_report_sorts_by_score_descending(tmp_path: Path) -> None:
    matches = [
        (_job_ad("a-1", "Niedrig"), _assessment(2)),
        (_job_ad("a-2", "Hoch"), _assessment(5)),
        (_job_ad("a-3", "Mittel"), _assessment(3)),
    ]

    path = _write_path(matches, date(2026, 11, 5), output_dir=tmp_path)

    assert path == tmp_path / "2026-11-05.md"
    content = path.read_text(encoding="utf-8")
    pos_high = content.index("Hoch")
    pos_mid = content.index("Mittel")
    pos_low = content.index("Niedrig")
    assert pos_high < pos_mid < pos_low


def test_matches_are_numbered_in_rank_order_from_one(tmp_path: Path) -> None:
    matches = [
        (_job_ad("a-1", "Niedrig"), _assessment(2)),
        (_job_ad("a-2", "Hoch"), _assessment(5)),
        (_job_ad("a-3", "Mittel"), _assessment(3)),
    ]

    written = write_report(matches, date(2026, 11, 5), output_dir=tmp_path)

    content = written.path.read_text(encoding="utf-8")
    assert "## 1. Hoch – Score 5/5" in content
    assert "## 2. Mittel – Score 3/5" in content
    assert "**3.** Niedrig" in content
    assert written.match_numbers == {"a-2": 1, "a-3": 2, "a-1": 3}


def test_matches_below_min_score_get_one_line(tmp_path: Path) -> None:
    matches = [
        (_job_ad("a-1", "Niedrig"), _assessment(2, "Zu weit weg.")),
        (_job_ad("a-2", "Grenzfall"), _assessment(3)),
    ]

    path = _write_path(matches, date(2026, 11, 5), output_dir=tmp_path, min_score=3)

    content = path.read_text(encoding="utf-8")
    assert "## 1. Grenzfall – Score 3/5" in content
    assert "## Weitere Treffer (Score unter 3)" in content
    assert (
        "- **2.** Niedrig (Beispiel GmbH, München) – Score 2/5: Zu weit weg. – "
        "https://www.arbeitsagentur.de/jobsuche/jobdetail/a-1\n"
    ) in content
    assert content.count("- Passt:") == 1


def test_only_low_matches_start_at_number_one(tmp_path: Path) -> None:
    matches = [(_job_ad("a-1", "Niedrig"), _assessment(1))]

    written = write_report(matches, date(2026, 11, 5), output_dir=tmp_path)

    assert "- **1.** Niedrig" in written.path.read_text(encoding="utf-8")
    assert written.match_numbers == {"a-1": 1}


def test_without_low_matches_compact_block_is_missing(tmp_path: Path) -> None:
    path = _write_path(
        [(_job_ad("a-1", "Niedrig"), _assessment(1))],
        date(2026, 11, 5),
        output_dir=tmp_path,
        min_score=1,
    )

    content = path.read_text(encoding="utf-8")
    assert "## 1. Niedrig" in content
    assert "Weitere Treffer" not in content


def test_compact_line_without_company_and_location(tmp_path: Path) -> None:
    job_ad = JobAd(id="a-1", title="Niedrig", company=None, location=None, link="https://x.example")

    path = _write_path([(job_ad, _assessment(1))], date(2026, 11, 5), output_dir=tmp_path)

    assert "Niedrig (unbekannt, unbekannt)" in path.read_text(encoding="utf-8")


def test_every_report_starts_again_at_one(tmp_path: Path) -> None:
    day = date(2026, 11, 5)
    write_report([(_job_ad("a-1", "Erster"), _assessment(4))], day, output_dir=tmp_path)

    second = write_report([(_job_ad("a-2", "Zweiter"), _assessment(3))], day, output_dir=tmp_path)

    assert second.match_numbers == {"a-2": 1}
    assert "## 1. Zweiter" in second.path.read_text(encoding="utf-8")


def test_report_without_matches_has_no_match_numbers(tmp_path: Path) -> None:
    written = write_report([], date(2026, 11, 5), output_dir=tmp_path)

    assert written.match_numbers == {}


def test_write_report_contains_all_required_fields(tmp_path: Path) -> None:
    matches = [(_job_ad("a-1", "Softwareentwickler"), _assessment(4, "Gute Passung."))]

    path = _write_path(matches, date(2026, 11, 5), output_dir=tmp_path)
    content = path.read_text(encoding="utf-8")

    assert "Softwareentwickler" in content
    assert "Beispiel GmbH" in content
    assert "München" in content
    assert "https://www.arbeitsagentur.de/jobsuche/jobdetail/a-1" in content
    assert "4/5" in content
    assert "Gute Passung." in content
    assert "Python" in content
    assert "Kubernetes" in content


def test_write_report_without_matches_writes_note_not_empty_file(tmp_path: Path) -> None:
    path = _write_path([], date(2026, 11, 5), output_dir=tmp_path)

    content = path.read_text(encoding="utf-8")
    assert "Keine neuen Treffer" in content
    assert len(content.strip()) > 0


def test_second_run_on_same_day_does_not_overwrite_first_report(tmp_path: Path) -> None:
    day = date(2026, 11, 5)
    first = _write_path([(_job_ad("a-1", "Erster Lauf"), _assessment(4))], day, output_dir=tmp_path)

    second = _write_path(
        [(_job_ad("a-2", "Zweiter Lauf"), _assessment(3))], day, output_dir=tmp_path
    )

    assert first == tmp_path / "2026-11-05.md"
    assert second == tmp_path / "2026-11-05-2.md"
    assert "Erster Lauf" in first.read_text(encoding="utf-8")
    assert "Zweiter Lauf" in second.read_text(encoding="utf-8")


def test_run_without_matches_does_not_overwrite_existing_report(tmp_path: Path) -> None:
    day = date(2026, 11, 5)
    first = _write_path([(_job_ad("a-1", "Erster Lauf"), _assessment(4))], day, output_dir=tmp_path)

    second = _write_path([], day, output_dir=tmp_path)

    assert second != first
    assert "Erster Lauf" in first.read_text(encoding="utf-8")


def test_third_run_on_same_day_gets_next_run_number(tmp_path: Path) -> None:
    day = date(2026, 11, 5)
    _write_path([], day, output_dir=tmp_path)
    _write_path([], day, output_dir=tmp_path)

    third = _write_path([], day, output_dir=tmp_path)

    assert third == tmp_path / "2026-11-05-3.md"


def test_source_status_comes_before_matches(tmp_path: Path) -> None:
    sources = [Quellenstatus("Arbeitnow", 3, []), Quellenstatus("Bundesagentur", 1, [])]

    path = _write_path(
        [(_job_ad("a-1", "Stelle"), _assessment(4))],
        date(2026, 11, 5),
        output_dir=tmp_path,
        sources=sources,
    )

    content = path.read_text(encoding="utf-8")
    assert "- Arbeitnow: 3 Anzeigen" in content
    assert "- Bundesagentur: 1 Anzeige\n" in content
    assert content.index("Arbeitnow") < content.index("## 1. Stelle")


def test_source_status_names_errors_even_with_partial_result(tmp_path: Path) -> None:
    sources = [Quellenstatus("Arbeitnow", 2, ["Data Scientist: HTTP 500", "IT: HTTP 503"])]

    path = _write_path([], date(2026, 11, 5), output_dir=tmp_path, sources=sources)

    assert "- Arbeitnow: FEHLER, 2 Anzeigen (Data Scientist: HTTP 500; IT: HTTP 503)" in (
        path.read_text(encoding="utf-8")
    )


def test_without_matches_source_failure_is_still_reported(tmp_path: Path) -> None:
    sources = [Quellenstatus("Arbeitnow", 0, ["IT: keine Verbindung"])]

    path = _write_path([], date(2026, 11, 5), output_dir=tmp_path, sources=sources)

    content = path.read_text(encoding="utf-8")
    assert "FEHLER" in content
    assert "Keine neuen Treffer" in content


_REJECTED = AlreadyApplied("absage", date(2026, 10, 1), "Text identisch")


def test_already_applied_is_in_own_block_at_end(tmp_path: Path) -> None:
    matches = [
        (_job_ad("a-1", "Beworben"), _assessment(5)),
        (_job_ad("a-2", "Offen"), _assessment(4)),
    ]

    path = _write_path(
        matches,
        date(2026, 11, 5),
        output_dir=tmp_path,
        applications={"a-1": _REJECTED},
    )

    content = path.read_text(encoding="utf-8")
    assert "## 1. Offen" in content
    assert "## Bereits beworben\n" in content
    assert (
        "- **2.** Beworben (Beispiel GmbH, München) – Score 5/5 – absage, beworben am "
        "01.10.2026 – Text identisch – https://www.arbeitsagentur.de/jobsuche/jobdetail/a-1\n"
    ) in content
    assert content.index("## 1. Offen") < content.index("## Bereits beworben")
    assert "## 2. Beworben" not in content


def test_match_numbers_run_across_all_blocks(tmp_path: Path) -> None:
    matches = [
        (_job_ad("a-1", "Beworben"), _assessment(5)),
        (_job_ad("a-2", "Voll"), _assessment(4)),
        (_job_ad("a-3", "Kompakt"), _assessment(1)),
    ]

    written = write_report(
        matches,
        date(2026, 11, 5),
        output_dir=tmp_path,
        applications={"a-1": _REJECTED},
    )

    assert written.match_numbers == {"a-2": 1, "a-3": 2, "a-1": 3}
    content = written.path.read_text(encoding="utf-8")
    assert content.index("Weitere Treffer") < content.index("Bereits beworben")


def test_without_applications_block_is_missing(tmp_path: Path) -> None:
    path = _write_path(
        [(_job_ad("a-1", "Offen"), _assessment(4))],
        date(2026, 11, 5),
        output_dir=tmp_path,
    )

    assert "Bereits beworben" not in path.read_text(encoding="utf-8")


def test_only_already_applied_matches(tmp_path: Path) -> None:
    written = write_report(
        [(_job_ad("a-1", "Beworben"), _assessment(2))],
        date(2026, 11, 5),
        output_dir=tmp_path,
        applications={"a-1": _REJECTED},
    )

    content = written.path.read_text(encoding="utf-8")
    assert "- **1.** Beworben" in content
    assert "Weitere Treffer" not in content
    assert written.match_numbers == {"a-1": 1}


def test_write_report_creates_output_dir(tmp_path: Path) -> None:
    target = tmp_path / "noch_nicht_vorhanden"

    _write_path([], date(2026, 11, 5), output_dir=target)

    assert target.is_dir()


def _follow_up(company: str | None = "Firma X", days_ago: int = 14) -> FollowUpReminder:
    day = date(2026, 11, 20) - timedelta(days=days_ago)
    return FollowUpReminder(company=company, title="Data Engineer", applied_on=day)


def test_follow_up_reminder_comes_after_sources_and_before_matches(tmp_path: Path) -> None:
    path = _write_path(
        [(_job_ad("a-1", "Stelle"), _assessment(4))],
        date(2026, 11, 20),
        output_dir=tmp_path,
        sources=[Quellenstatus("Arbeitnow", 0, [])],
        follow_ups=[_follow_up()],
    )

    content = path.read_text(encoding="utf-8")
    assert "## Nachfassen\n" in content
    assert (
        "- Data Engineer (Firma X): seit 14 Tagen keine Antwort, nachhaken? "
        "(beworben am 06.11.2026)\n"
    ) in content
    assert (
        content.index("## Quellen") < content.index("## Nachfassen") < content.index("## 1. Stelle")
    )


def test_follow_up_reminder_appears_without_matches(tmp_path: Path) -> None:
    path = _write_path([], date(2026, 11, 20), output_dir=tmp_path, follow_ups=[_follow_up()])

    content = path.read_text(encoding="utf-8")
    assert "## Nachfassen" in content
    assert "Keine neuen Treffer" in content


def test_without_reminders_follow_up_block_is_missing(tmp_path: Path) -> None:
    path = _write_path([], date(2026, 11, 20), output_dir=tmp_path)

    assert "Nachfassen" not in path.read_text(encoding="utf-8")


def test_follow_up_reminder_without_company_and_one_day(tmp_path: Path) -> None:
    path = _write_path(
        [],
        date(2026, 11, 20),
        output_dir=tmp_path,
        follow_ups=[_follow_up(company=None, days_ago=1)],
    )

    assert "Data Engineer (unbekannt): seit 1 Tag keine Antwort" in path.read_text(encoding="utf-8")


def test_profile_suggestion_hint_comes_after_follow_ups(tmp_path: Path) -> None:
    path = _write_path(
        [],
        date(2026, 11, 20),
        output_dir=tmp_path,
        follow_ups=[_follow_up()],
        open_feedback=5,
    )

    content = path.read_text(encoding="utf-8")
    assert (
        "## Profil-Vorschlag\n- 5 Rückmeldungen warten auf Auswertung: "
        "`python -m jobagent.profilvorschlag`\n"
    ) in content
    assert content.index("## Nachfassen") < content.index("## Profil-Vorschlag")


def test_without_open_feedback_no_hint(tmp_path: Path) -> None:
    path = _write_path([], date(2026, 11, 20), output_dir=tmp_path)

    assert "Profil-Vorschlag" not in path.read_text(encoding="utf-8")
