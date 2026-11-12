"""Golden-File-Test: Der Report des Demo-Laufs bleibt zeichengleich mit dem Snapshot.

Der Snapshot liegt in `tests/fixtures/demo_report.md`. Der Lauf bekommt ein festes Datum,
damit Report-Datum und Tage seit einer Bewerbung an jedem Tag gleich sind.

Gewollte Änderung am Report: Snapshot neu schreiben mit

    JOBAGENT_UPDATE_SNAPSHOT=1 uv run pytest tests/test_demo_snapshot.py

und den Diff von `tests/fixtures/demo_report.md` im Commit prüfen.
"""

import difflib
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from jobagent import main

SNAPSHOT = Path(__file__).parent / "fixtures" / "demo_report.md"
UPDATE_SWITCH = "JOBAGENT_UPDATE_SNAPSHOT"
FIXED_DAY = date(2026, 3, 2)


@pytest.fixture
def demo_report(fixed_today: Callable[[date], None]) -> str:
    """Report eines Demo-Laufs am festen Tag `FIXED_DAY`."""
    fixed_today(FIXED_DAY)
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


def _assert_matches_snapshot(report: str, snapshot: Path) -> None:
    """Vergleicht zeichengleich; bei Abweichung schlägt der Test mit Unified Diff fehl."""
    if not snapshot.exists():
        pytest.fail(f"Snapshot fehlt. Anlegen mit {UPDATE_SWITCH}=1.", pytrace=False)
    with snapshot.open(encoding="utf-8", newline="") as file:
        expected = file.read()

    if report != expected:
        pytest.fail(
            f"Demo-Report weicht vom Snapshot ab. Gewollt? Neu schreiben mit "
            f"{UPDATE_SWITCH}=1.\n{_diff(expected, report)}",
            pytrace=False,
        )


def test_demo_report_matches_snapshot(demo_report: str) -> None:
    if os.environ.get(UPDATE_SWITCH) == "1":
        SNAPSHOT.write_text(demo_report, encoding="utf-8", newline="")
        pytest.skip(f"Snapshot neu geschrieben: {SNAPSHOT.name}")

    _assert_matches_snapshot(demo_report, SNAPSHOT)


def test_differing_report_line_fails_with_unified_diff(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.md"
    snapshot.write_text("# Report\nScore 4/5\nEnde\n", encoding="utf-8", newline="")

    with pytest.raises(pytest.fail.Exception) as failure:
        _assert_matches_snapshot("# Report\nScore 5/5\nEnde\n", snapshot)

    message = str(failure.value)
    assert f"{UPDATE_SWITCH}=1" in message
    assert "--- Snapshot\n+++ Demo-Lauf\n" in message
    assert "@@ -1,3 +1,3 @@\n # Report\n-Score 4/5\n+Score 5/5\n Ende\n" in message
