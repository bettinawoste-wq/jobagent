"""Logging der Kommandos: eingerichtet nur an den Einstiegspunkten.

Die Konsole zeigt ab INFO. Der Agent selbst loggt auch auf DEBUG, etwa den Traceback eines
Abbruchs, das sieht aber nur eine Log-Datei des Laufs (`RunLog`). Fremde Bibliotheken bleiben
bei INFO: Das SDK von Anthropic loggt auf DEBUG ganze Anfragen samt Anzeigen-Volltext, und
der gehört in kein Log (ADR 0001).
"""

import logging
import sys
from pathlib import Path

_CONSOLE_FORMAT = "%(levelname)s:%(name)s:%(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Die eigenen Logger; ein Kommando, das mit `python -m` startet, loggt als `__main__`.
_OWN_LOGGERS = ("jobagent", "__main__")

_console: logging.Handler | None = None


def setup_logging() -> None:
    """Richtet das Logging eines Kommandos ein; ein zweiter Aufruf ersetzt den ersten."""
    global _console
    root = logging.getLogger()
    if _console is not None:
        root.removeHandler(_console)
    _console = logging.StreamHandler(sys.stderr)
    _console.setLevel(logging.INFO)
    _console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    root.addHandler(_console)
    root.setLevel(logging.INFO)
    for name in _OWN_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)


class RunLog(logging.Handler):
    """Sammelt das Log eines Laufs ab DEBUG, bis feststeht, wie die Log-Datei heißt.

    Der Name des Reports steht erst fest, wenn er geschrieben ist; bis dahin bleibt das Log
    im Speicher. So entsteht nie eine Log-Datei zu einem Report, den es nicht gibt.
    """

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.setFormatter(logging.Formatter(_FILE_FORMAT))
        self._lines: list[str] = []
        # Fremde Bibliotheken nur ab INFO, auch wenn jemand ihr DEBUG einschaltet: Das SDK
        # von Anthropic loggt dort ganze Anfragen samt Anzeigen-Volltext.
        self.addFilter(_only_own_debug)

    def __enter__(self) -> "RunLog":
        logging.getLogger().addHandler(self)
        return self

    def __exit__(self, *exc_info: object) -> None:
        logging.getLogger().removeHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._lines.append(self.format(record) + "\n")
        except Exception:
            self.handleError(record)  # ein kaputter Log-Aufruf darf den Lauf nicht abbrechen

    def save(self, path: Path, *, append: bool = False) -> None:
        """Schreibt das gesammelte Log nach `path`; mit `append` hinten an eine vorhandene Datei.

        Lässt sich die Datei nicht schreiben, steht eine Warnung auf der Konsole; der Lauf
        selbst gilt deshalb nicht als gescheitert.
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with path.open(mode, encoding="utf-8", errors="backslashreplace") as file:
                file.writelines(self._lines)
        except OSError as error:
            logging.getLogger(__name__).warning(
                "Log-Datei ließ sich nicht schreiben (datei=%s): %s", path, error
            )


def _only_own_debug(record: logging.LogRecord) -> bool:
    """DEBUG nur von den eigenen Loggern, alles ab INFO von allen."""
    return record.levelno >= logging.INFO or record.name.split(".")[0] in _OWN_LOGGERS
