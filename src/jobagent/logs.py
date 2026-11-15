"""Logging der Kommandos: eingerichtet nur an den Einstiegspunkten.

Die Konsole zeigt ab INFO. Der Agent selbst loggt auch auf DEBUG, etwa den Traceback eines
Abbruchs, das sieht aber nur eine Log-Datei des Laufs (`RunLog`). Fremde Bibliotheken bleiben
bei INFO: Das SDK von Anthropic loggt auf DEBUG ganze Anfragen samt Anzeigen-Volltext, und
der gehört in kein Log (ADR 0001).
"""

import logging
import sys
from pathlib import Path
from typing import TextIO

_CONSOLE_FORMAT = "%(levelname)s:%(name)s:%(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_console: logging.Handler | None = None


def setup_logging() -> None:
    """Richtet das Logging eines Kommandos ein; ein zweiter Aufruf ersetzt den ersten."""
    global _console
    root = logging.getLogger()
    if _console is not None:
        root.removeHandler(_console)
    _console = _Console()
    _console.setLevel(logging.INFO)
    _console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    root.addHandler(_console)
    root.setLevel(logging.INFO)
    logging.getLogger("jobagent").setLevel(logging.DEBUG)


class _Console(logging.StreamHandler):
    # Schreibt immer in das aktuelle sys.stderr, auch wenn es nach dem Einrichten ersetzt wird.
    @property
    def stream(self) -> TextIO:  # type: ignore[override]
        return sys.stderr

    @stream.setter
    def stream(self, value: TextIO) -> None:
        pass


class RunLog(logging.Handler):
    """Sammelt das Log eines Laufs ab DEBUG, bis feststeht, wie die Log-Datei heißt.

    Der Name des Reports steht erst fest, wenn er geschrieben ist; bis dahin bleibt das Log
    im Speicher. So entsteht nie eine Log-Datei zu einem Report, den es nicht gibt.
    """

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.setFormatter(logging.Formatter(_FILE_FORMAT))
        self._lines: list[str] = []

    def __enter__(self) -> "RunLog":
        logging.getLogger().addHandler(self)
        return self

    def __exit__(self, *exc_info: object) -> None:
        logging.getLogger().removeHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        self._lines.append(self.format(record) + "\n")

    def save(self, path: Path) -> None:
        """Schreibt das gesammelte Log nach `path` und hängt an, falls es die Datei schon gibt.

        Lässt sich die Datei nicht schreiben, steht eine Warnung auf der Konsole; der Lauf
        selbst gilt deshalb nicht als gescheitert.
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as file:
                file.writelines(self._lines)
        except OSError as error:
            logging.getLogger(__name__).warning(
                "Log-Datei ließ sich nicht schreiben (datei=%s): %s", path, error
            )
