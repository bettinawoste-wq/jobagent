"""Das Suchprofil aus `profile.md`, gelesen von Lauf und Profil-Vorschlag.

Geschrieben wird es nur, wenn die Nutzerin einem Profil-Vorschlag zustimmt (ADR 0003).
"""

import errno
import os
import shutil
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path


class SearchProfileError(Exception):
    """Das Suchprofil fehlt, ist nicht lesbar oder lässt sich nicht ändern.

    Die Meldung nennt die Datei.
    """


def read_search_profile(path: Path) -> str:
    """Liest das Suchprofil; wirft `SearchProfileError`, wenn das nicht geht."""
    try:
        # "utf-8-sig": Windows-Editoren setzen gern ein BOM vor UTF-8, das gehört nicht dazu.
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise SearchProfileError(
            f"Suchprofil {path} nicht gefunden. Vorlage: profile.example.md"
        ) from None
    except UnicodeDecodeError as error:
        raise SearchProfileError(
            f"Suchprofil {path} ist nicht in UTF-8 gespeichert; bitte als UTF-8 speichern."
        ) from error
    except OSError as error:
        raise SearchProfileError(
            f"Suchprofil {path} nicht lesbar: {error.strerror or error}"
        ) from error


def replace_search_profile(path: Path, new: str, *, previous: str, now: datetime) -> Path:
    """Sichert `previous` und ersetzt das Suchprofil unter `path` durch `new`.

    Ist `path` eine Verknüpfung, gilt alles für die Datei dahinter. Die Sicherung liegt
    daneben, nur für die Nutzerin lesbar, heißt nach `now` und überschreibt nie eine
    vorhandene Datei. Das neue Suchprofil entsteht als eigene Datei daneben und ersetzt das
    alte in einem Schritt, mit dessen Rechte-Bits (nicht Eigentümer, ACLs oder harte
    Verknüpfungen). Scheitert etwas, bleibt das alte Suchprofil ganz; scheitert es oder
    bricht man mit Strg+C ab, wird die Sicherung wieder entfernt. Nach einem harten Abbruch
    (Absturz, Stromausfall) können Sicherung und `<name>.*.neu` liegen bleiben. Ein
    schreibgeschütztes Suchprofil bleibt, wie es ist. Gibt die Sicherung zurück; scheitert
    etwas, wirft `SearchProfileError`.
    """
    created: list[Path] = []  # was weg muss, wenn das Ersetzen nicht gelingt
    replaced = False
    try:
        target = path.resolve(strict=True)
        if not os.access(target, os.W_OK):
            raise PermissionError(errno.EACCES, "schreibgeschützt")
        backup = target.with_name(f"{target.stem}.sicherung-{now:%Y-%m-%d-%H%M%S}{target.suffix}")
        backup_fd = os.open(backup, _NEW_PRIVATE_FILE, 0o600)
        created.append(backup)
        _fill(backup_fd, previous)
        # Eigener Name je Versuch, damit kein Rest eines abgebrochenen Versuchs stört.
        draft_fd, draft_name = tempfile.mkstemp(
            prefix=f"{target.name}.", suffix=".neu", dir=target.parent
        )
        draft = Path(draft_name)
        created.append(draft)
        _fill(draft_fd, new)
        with suppress(OSError):  # manche Dateisysteme (SMB, FUSE) setzen keine Rechte-Bits
            shutil.copymode(target, draft)
        draft.replace(target)
        replaced = True
    # RuntimeError: Schleife aus Verknüpfungen; UnicodeError: Text, den UTF-8 nicht kann
    except (OSError, RuntimeError, UnicodeError) as error:
        reason = error.strerror if isinstance(error, OSError) and error.strerror else error
        raise SearchProfileError(f"Suchprofil {path} ließ sich nicht ändern: {reason}") from error
    finally:
        if not replaced:  # auch bei Strg+C: keine Sicherung zu einer Änderung, die es nicht gab
            for leftover in created:
                with suppress(OSError):
                    leftover.unlink()
    _sync_folder(target.parent)
    return backup


# Nur neu anlegen (nie überschreiben, keiner untergeschobenen Verknüpfung folgen); angelegt
# wird nur für die Nutzerin lesbar, denn es steht das Suchprofil darin.
_NEW_PRIVATE_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL


def _fill(fd: int, text: str) -> None:
    # Über den Deskriptor, mit dem die Datei angelegt wurde, nicht erneut über den Pfad.
    # fsync: erst auf der Platte, dann ersetzen; sonst können nach einem Stromausfall
    # Suchprofil oder Sicherung leer sein.
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())


def _sync_folder(folder: Path) -> None:
    # Damit auch das Ersetzen selbst einen Stromausfall übersteht. Windows kann Ordner
    # nicht öffnen; misslingt es, ist das Suchprofil trotzdem geändert.
    if os.name == "nt":
        return
    with suppress(OSError):
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
