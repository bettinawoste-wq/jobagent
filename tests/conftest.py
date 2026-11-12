"""Gemeinsame Fixtures der Tests."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from jobagent import main


@pytest.fixture
def fixed_today(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[date], None]:
    """Feste Uhr für den Lauf: Der Aufruf mit einem Tag macht ihn zu "heute".

    Der Lauf liest das Datum nur über `main.date` (Report-Datum und, im Demo-Lauf, die
    Bewerbungsdaten). Arbeitsordner ist `tmp_path`, damit nichts im Projekt landet.
    """
    monkeypatch.chdir(tmp_path)

    def set_today(day: date) -> None:
        class FixedDate(date):
            @classmethod
            def today(cls) -> date:
                return day

        monkeypatch.setattr(main, "date", FixedDate)

    return set_today
