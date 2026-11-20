"""Sperre gegen gleichzeitige Läufe.

Die Sperre ist eine Sperre des Betriebssystems auf einer Sperrdatei, keine bloße Datei: Endet
der Prozess, auch durch Absturz oder hartes Beenden, gibt das Betriebssystem sie frei. Die
Sperrdatei selbst bleibt liegen und stört nicht; sie wird beim nächsten Lauf wieder gesperrt.
"""

import contextlib
import errno
import os
import sys
from pathlib import Path
from types import TracebackType

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class RunLockFileError(Exception):
    """Die Sperrdatei lässt sich nicht öffnen oder sperren; der Lauf bricht ab."""


class RunLockedError(Exception):
    """Ein anderer Lauf hält die Sperre; dieser Lauf bricht ab."""


class RunLock:
    """Sperrt die Sperrdatei neben einer Datenbank für die Dauer des `with`-Blocks.

    Gewartet wird nicht: Hält schon ein anderer Lauf die Sperre, scheitert der Eintritt mit
    `RunLockedError`, lässt sich die Sperrdatei nicht öffnen oder sperren, mit `RunLockFileError`.
    """

    def __init__(self, db_path: Path) -> None:
        # Neben der Datenbank: Wer dieselbe Datenbank nutzt, nutzt auch dieselbe Sperre. Nicht
        # `<db>.lock`: Den Namen nutzt SQLite auf manchen Dateisystemen für eigene Sperren.
        self._path = db_path.with_name(db_path.name + ".runlock")
        self._fd: int | None = None

    def __enter__(self) -> "RunLock":
        try:
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as error:
            raise RunLockFileError(f"Sperrdatei {self._path} nicht nutzbar: {error}") from error
        try:
            _lock(fd)
        except OSError as error:
            os.close(fd)
            if error.errno not in _HELD_ELSEWHERE:
                raise RunLockFileError(f"Sperrdatei {self._path} nicht nutzbar: {error}") from error
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
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        # Scheitert das Freigeben, gibt spätestens das Schließen oder das Ende des Prozesses die
        # Sperre frei; ein Fehler hier soll weder den Fehler noch den Report des Laufs verdecken.
        with contextlib.suppress(OSError):
            _unlock(fd)
        with contextlib.suppress(OSError):
            os.close(fd)


# Fehlernummern, mit denen das Sperren scheitert, weil ein anderer die Sperre hält: unter
# Linux EWOULDBLOCK (gleich EAGAIN), wo flock auf fcntl aufsetzt auch EACCES, unter Windows
# EACCES oder EDEADLOCK. Windows meldet
# allerdings jedes Scheitern als EACCES; dort lässt sich ein belegter Lauf nicht von einer
# Sperrdatei unterscheiden, die sich nicht sperren lässt.
_HELD_ELSEWHERE = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES}
if sys.platform == "win32":
    _HELD_ELSEWHERE.add(errno.EDEADLOCK)


def _lock(fd: int) -> None:
    """Sperrt `fd` exklusiv und ohne Warten; ist sie schon gesperrt, kommt `OSError`."""
    if sys.platform == "win32":
        # Sperrt das erste Byte, auch wenn die Datei leer ist.
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    # Ausdrücklich freigeben: Windows gibt die Sperre beim Schließen sonst unter Umständen erst
    # verzögert frei, und ein gleich danach startender Lauf hielte sie noch für belegt.
    if sys.platform == "win32":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
