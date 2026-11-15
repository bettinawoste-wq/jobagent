"""Gemeinsame Fixtures der Tests."""

import logging
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from jobagent import logs, main


@pytest.fixture
def fixed_today(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[date], None]:
    """Feste Uhr für den Zusammenbau: Der Aufruf mit einem Tag macht ihn zu "heute".

    Der Zusammenbau liest das Datum nur über `main.date` (Report-Datum und, im Demo-Lauf, die
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


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """Die Kommandos richten das Logging prozessweit ein; nach jedem Test gilt wieder das alte."""
    loggers = [logging.getLogger(name) for name in (None, *logs._OWN_LOGGERS)]
    levels = [logger.level for logger in loggers]
    yield
    if logs._console is not None:
        logging.getLogger().removeHandler(logs._console)
        logs._console = None
    for logger, level in zip(loggers, levels, strict=True):
        logger.setLevel(level)
