"""Golden-File-Test: Der Report des Demo-Laufs bleibt zeichengleich mit dem Snapshot.

Der Snapshot liegt in `tests/fixtures/demo_report.md`. Der Lauf bekommt ein festes Datum,
damit Report-Datum und Tage seit einer Bewerbung an jedem Tag gleich sind.

Gewollte Änderung am Report: Snapshot neu schreiben mit

    JOBAGENT_UPDATE_SNAPSHOT=1 uv run pytest tests/test_demo_snapshot.py

und den Diff von `tests/fixtures/demo_report.md` im Commit prüfen.
"""

import difflib
import os
from datetime import date
from pathlib import Path

import pytest

from jobagent import main

SNAPSHOT = Path(__file__).parent / "fixtures" / "demo_report.md"
UPDATE_SWITCH = "JOBAGENT_UPDATE_SNAPSHOT"
FIXED_DAY = date(2026, 3, 2)


@pytest.fixture
def demo_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Report eines Demo-Laufs am festen Tag `FIXED_DAY`."""

    class FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return FIXED_DAY

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "date", FixedDate)
    return main.demo_run()


def _diff(expected: str, actual: str) -> str:
    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile="Snapshot",
            tofile="Demo-Lauf",
        )
    )


def test_demo_report_matches_snapshot(demo_report: str) -> None:
    if os.environ.get(UPDATE_SWITCH) == "1":
        SNAPSHOT.write_text(demo_report, encoding="utf-8", newline="")
        pytest.skip(f"Snapshot neu geschrieben: {SNAPSHOT.name}")

    if not SNAPSHOT.exists():
        pytest.fail(f"Snapshot fehlt. Anlegen mit {UPDATE_SWITCH}=1.", pytrace=False)
    with SNAPSHOT.open(encoding="utf-8", newline="") as file:
        expected = file.read()

    if demo_report != expected:
        pytest.fail(
            f"Demo-Report weicht vom Snapshot ab. Gewollt? Neu schreiben mit "
            f"{UPDATE_SWITCH}=1.\n{_diff(expected, demo_report)}",
            pytrace=False,
        )
