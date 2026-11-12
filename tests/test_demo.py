"""Tests fuer den Demo-Lauf (`--demo`), beobachtet ueber stdout und Dateien."""

import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest

from jobagent import main, score


@pytest.fixture
def empty_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Frischer Clone: kein API-Key, keine profile.md, keine config.toml, kein Netz, kein Modell."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Demo-Lauf darf nicht ins Netz")

    def no_model(*args: object, **kwargs: object) -> None:
        raise AssertionError("Demo-Lauf darf kein Modell fragen")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(score, "score_job_ad", no_model)
    return tmp_path


def _demo_run(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    main.cli(["--demo", *argv])
    return capsys.readouterr().out


def test_demo_run_prints_report_without_creating_anything(
    empty_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _demo_run(capsys)

    assert output.startswith("# Stellenvorschläge ")
    assert list(empty_project.iterdir()) == []


def test_demo_run_shows_scores_from_1_to_5(
    empty_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _demo_run(capsys)

    for score_value in range(1, 6):
        assert f"Score {score_value}/5" in output


def test_demo_run_shows_weak_matches_on_one_line(
    empty_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _demo_run(capsys)

    compact = output.split("## Weitere Treffer (Score unter 3)\n")[1]
    assert "SAP-Berater FI/CO (m/w/d) (Musterfirma Beratung GmbH, Beispielstadt)" in compact
    assert "Score 1/5" in compact


def test_demo_run_reports_failed_source_and_continues(
    empty_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _demo_run(capsys)

    assert (
        "- Firmen-Watchlist (Demo): FEHLER, 2 Anzeigen (Musterwerk AG: Board nicht erreichbar)"
        in output
    )
    assert "- Bundesagentur für Arbeit (Demo): 3 Anzeigen" in output


def test_demo_run_shows_follow_up_reminder(
    empty_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _demo_run(capsys)

    assert "## Nachfassen\n" in output
    assert "seit 18 Tagen keine Antwort, nachhaken?" in output


def test_demo_run_detects_applied_position_whose_text_differs(
    empty_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _demo_run(capsys)

    applied = output.split("## Bereits beworben\n")[1]
    assert "Python Developer (w/m/d) (Beispiel Tech, Remote)" in applied
    assert "gespräch, beworben am" in applied
    assert "Text weicht von deiner Bewerbung ab" in applied


def test_demo_run_with_output_also_writes_a_file(
    empty_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _demo_run(capsys, "--ausgabe", "demo-report")

    files = list((empty_project / "demo-report").iterdir())
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == output
    assert [entry.name for entry in empty_project.iterdir()] == ["demo-report"]


def test_output_only_exists_in_demo_run(empty_project: Path) -> None:
    with pytest.raises(SystemExit):
        main.cli(["--ausgabe", "demo-report"])


def _demo_run_on(
    day: date, capsys: pytest.CaptureFixture[str], fixed_today: Callable[[date], None]
) -> str:
    fixed_today(day)
    return _demo_run(capsys)


def _without_dates(text: str) -> str:
    return re.sub(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}", "<datum>", text)


def test_demo_run_is_the_same_every_day_except_dates(
    empty_project: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_today: Callable[[date], None],
) -> None:
    in_winter = _demo_run_on(date(2026, 1, 5), capsys, fixed_today)
    in_summer = _demo_run_on(date(2027, 7, 31), capsys, fixed_today)

    assert "2026-01-05" in in_winter
    assert "2027-07-31" in in_summer
    assert _without_dates(in_winter) == _without_dates(in_summer)


def test_demo_run_links_only_to_example_com(
    empty_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _demo_run(capsys)

    links = re.findall(r"https?://\S+", output)
    assert len(links) == 8
    assert all(link.startswith("https://example.com/") for link in links)


def test_demo_run_prints_umlauts_as_utf8(tmp_path: Path) -> None:
    # Eigener Prozess ohne UTF-8-Vorgaben, so wie die Windows-Konsole ihn startet.
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in {"PYTHONIOENCODING", "PYTHONUTF8", "ANTHROPIC_API_KEY"}
    }
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    result = subprocess.run(
        [sys.executable, "-m", "jobagent.main", "--demo"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        check=True,
    )

    assert "# Stellenvorschläge" in result.stdout.decode("utf-8")
    assert list(tmp_path.iterdir()) == []
