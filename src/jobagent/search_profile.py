"""Das Suchprofil aus `profile.md`, gelesen von Lauf und Profil-Vorschlag."""

from pathlib import Path


class SearchProfileError(Exception):
    """Das Suchprofil fehlt oder ist nicht lesbar; die Meldung nennt die Datei."""


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
