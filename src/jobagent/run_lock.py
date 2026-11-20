"""Sperre gegen gleichzeitige Läufe.

Die Sperre ist eine Sperre des Betriebssystems auf einer Sperrdatei, keine bloße Datei: Endet
der Prozess, auch durch Absturz oder hartes Beenden, gibt das Betriebssystem sie frei. Die
Sperrdatei selbst bleibt liegen und stört nicht; sie wird beim nächsten Lauf wieder gesperrt.
"""

import os
import sys
from pathlib import Path
from types import TracebackType

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class RunLockedError(Exception):
    """Ein anderer Lauf hält die Sperre; dieser Lauf bricht ab."""


class RunLock:
    """Sperrt `path` für die Dauer des `with`-Blocks, ohne zu warten.

    Hält schon ein anderer Lauf die Sperre, scheitert der Eintritt mit `RunLockedError`.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> "RunLock":
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            _lock(fd)
        except OSError as error:
            os.close(fd)
            raise RunLockedError(
                "Es läuft schon ein anderer Lauf; dieser bricht ab. "
                "Starte ihn erneut, wenn der andere fertig ist."
            ) from error
        self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            os.close(self._fd)  # gibt die Sperre mit frei
            self._fd = None


def _lock(fd: int) -> None:
    """Sperrt `fd` exklusiv und ohne Warten; ist sie schon gesperrt, kommt `OSError`."""
    if sys.platform == "win32":
        # Sperrt das erste Byte, auch wenn die Datei leer ist.
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
