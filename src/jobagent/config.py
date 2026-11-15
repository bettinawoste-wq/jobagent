"""Konfiguration eines Laufs aus `config.toml`."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from jobagent.report import DEFAULT_MIN_SCORE
from jobagent.sources.watchlist import WatchlistCompany


@dataclass(frozen=True)
class Config:
    """Konfiguration eines Laufs; in `config.toml` stehen die Schlüssel deutsch."""

    keywords: list[str] = field(default_factory=list)
    location: str | None = None
    radius: int | None = None
    published_since: int | None = None
    min_score: int = DEFAULT_MIN_SCORE
    follow_up_min_days: int = 14
    follow_up_max_days: int = 28
    companies: list[WatchlistCompany] = field(default_factory=list)


class ConfigError(Exception):
    """`config.toml` fehlt, ist kaputt, oder ein Schlüssel steht nicht an seinem Platz."""


# Die einzige Stelle, an der die deutschen Schlüssel aus `config.toml` übersetzt werden:
# (Abschnitt, Schlüssel) -> Feld von `Config`.
_TOML_KEYS = {
    ("suche", "was"): "keywords",
    ("suche", "wo"): "location",
    ("suche", "veroeffentlichtseit"): "published_since",
    ("bundesagentur", "umkreis"): "radius",
    ("watchlist", "firmen"): "companies",
    ("report", "mindest_score"): "min_score",
    ("report", "nachfassen_ab_tag"): "follow_up_min_days",
    ("report", "nachfassen_bis_tag"): "follow_up_max_days",
}
# Abschnitt, in den ein deutscher Schlüssel gehört.
_SECTION_OF_KEY = {german: section for section, german in _TOML_KEYS}
_SECTIONS = set(_SECTION_OF_KEY.values())


def load_config(path: Path) -> Config:
    """Liest `config.toml`; fehlende Abschnitte und Schlüssel behalten ihren Standardwert.

    Steht ein bekannter Schlüssel oben in der Datei wie im alten flachen Format oder in einem
    anderen bekannten Abschnitt, bricht das Laden mit `ConfigError` ab und nennt seinen Platz.
    Unbekannte Abschnitte und Schlüssel werden nicht geprüft. Fehlt die Datei, ist sie
    nicht lesbar oder kein gültiges TOML, wirft das Laden ebenfalls `ConfigError`.
    """
    raw = _read_toml(path)
    _reject_misplaced(raw, path)
    values = {
        english: raw[section][german]
        for (section, german), english in _TOML_KEYS.items()
        if german in raw.get(section, {})
    }
    if "companies" in values:
        values["companies"] = [_to_company(entry) for entry in values["companies"]]
    return Config(**values)


def _read_toml(path: Path) -> dict:
    try:
        # "utf-8-sig": Windows-Editoren setzen gern ein BOM vor UTF-8, TOML erlaubt keines.
        return tomllib.loads(path.read_bytes().decode("utf-8-sig"))
    except FileNotFoundError:
        raise ConfigError(f"{path} nicht gefunden.") from None
    except OSError as error:
        raise ConfigError(f"{path} nicht lesbar: {error.strerror or error}") from error
    except UnicodeDecodeError as error:
        raise ConfigError(
            f"{path} ist nicht in UTF-8 gespeichert; bitte als UTF-8 speichern."
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} ist kein gültiges TOML: {error}") from error


def _reject_misplaced(raw: dict, path: Path) -> None:
    problems = [
        *_flat_keys(raw),
        *_sections_without_table(raw),
        *_keys_in_other_section(raw),
        *_companies_without_tables(raw),
    ]
    if problems:
        flat = any(key in _SECTION_OF_KEY for key in raw)
        hint = " Das alte flache Format ohne Abschnitte wird nicht mehr gelesen." if flat else ""
        raise ConfigError(
            f"{path} ist nicht richtig gegliedert: " + "; ".join(problems) + "." + hint
        )


def _flat_keys(raw: dict) -> list[str]:
    # Bekannte Schlüssel oben in der Datei, wie im alten flachen Format.
    return [
        f"`{key}` gehört unter `{_place(_SECTION_OF_KEY[key], key)}`"
        for key in raw
        if key in _SECTION_OF_KEY
    ]


def _sections_without_table(raw: dict) -> list[str]:
    return [
        f"`{key}` muss ein Abschnitt `[{key}]` sein"
        for key, value in raw.items()
        if key in _SECTIONS and not isinstance(value, dict)
    ]


def _keys_in_other_section(raw: dict) -> list[str]:
    return [
        f"`{_spelling(section, german, bool(value) and _is_list_of_tables(value))}` gehört "
        f"unter `{_place(_SECTION_OF_KEY[german], german)}`"
        for section, german, value in _known_keys_in_sections(raw)
        if _SECTION_OF_KEY[german] != section
    ]


def _companies_without_tables(raw: dict) -> list[str]:
    return [
        f"`[{section}] {german}` muss als `{_place(section, german)}` stehen"
        for section, german, value in _known_keys_in_sections(raw)
        if _SECTION_OF_KEY[german] == section
        and _is_companies(section, german)
        and not _is_list_of_tables(value)
    ]


def _known_keys_in_sections(raw: dict) -> list[tuple[str, str, object]]:
    """Bekannte Schlüssel in bekannten Abschnitten als (Abschnitt, Schlüssel, Wert)."""
    return [
        (section, german, value)
        for section, table in raw.items()
        if section in _SECTIONS and isinstance(table, dict)
        for german, value in table.items()
        if german in _SECTION_OF_KEY
    ]


def _place(section: str, german: str) -> str:
    """So wird der Schlüssel an seinem Platz geschrieben."""
    return _spelling(section, german, list_of_tables=_is_companies(section, german))


def _spelling(section: str, german: str, list_of_tables: bool) -> str:
    """So steht ein Schlüssel in der Datei: als Liste von Tabellen oder im Abschnitt."""
    if list_of_tables:
        return f"[[{section}.{german}]]"
    return f"[{section}] {german}"


def _is_companies(section: str, german: str) -> bool:
    # Die Firmen der Watchlist sind der einzige Eintrag, der eine Liste von Tabellen ist.
    return _TOML_KEYS[(section, german)] == "companies"


def _is_list_of_tables(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def _to_company(entry: dict) -> WatchlistCompany:
    # Fehlt etwas, scheitert erst die Suche dieser Firma, nicht das Laden der Konfiguration.
    slug = entry.get("slug", "")
    return WatchlistCompany(name=entry.get("name", slug), ats=entry.get("ats", ""), slug=slug)
