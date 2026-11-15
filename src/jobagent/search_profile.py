"""Das Suchprofil aus `profile.md`, gelesen von Lauf und Profil-Vorschlag.

Geschrieben wird es nur, wenn die Nutzerin einem Profil-Vorschlag zustimmt (ADR 0003).
"""

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
    """Sichert `previous` neben `path` und schreibt `new` nach `path`; gibt die Sicherung zurück.

    Die Sicherung heißt nach `now` und überschreibt nie eine vorhandene Datei. Scheitert eins
    davon, wirft `SearchProfileError`.
    """
    backup = path.with_name(f"{path.stem}.sicherung-{now:%Y-%m-%d-%H%M%S}{path.suffix}")
    try:
        with backup.open("x", encoding="utf-8") as file:  # "x": nie überschreiben
            file.write(previous)
        path.write_text(new, encoding="utf-8")
    except OSError as error:
        raise SearchProfileError(
            f"Suchprofil {path} ließ sich nicht ändern: {error.strerror or error}"
        ) from error
    return backup
