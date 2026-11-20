"""Konfiguration eines Laufs aus `config.toml`."""

import difflib
import tomllib
from collections.abc import Callable
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
    """`config.toml` fehlt, ist kaputt, oder ein Abschnitt oder Schlüssel passt nicht."""


@dataclass(frozen=True)
class _ValueType:
    """Erwarteter Typ eines Werts in `config.toml`, in Worten für die Meldung."""

    words: str
    accepts: Callable[[object], bool]


def _is_whole_number(value: object) -> bool:
    # TOML-Wahrheitswerte sind in Python `bool` und damit auch `int`.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_list_of_texts(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_list_of_tables(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


_TEXT = _ValueType("ein Text", lambda value: isinstance(value, str))
_WHOLE_NUMBER = _ValueType("eine ganze Zahl", _is_whole_number)
_LIST_OF_TEXTS = _ValueType("eine Liste von Texten", _is_list_of_texts)
_LIST_OF_TABLES = _ValueType("eine Liste von Tabellen", _is_list_of_tables)

# Die einzige Stelle, an der die deutschen Schlüssel aus `config.toml` übersetzt werden:
# (Abschnitt, Schlüssel) -> (Feld von `Config`, erwarteter Typ).
_TOML_KEYS: dict[tuple[str, str], tuple[str, _ValueType]] = {
    ("suche", "was"): ("keywords", _LIST_OF_TEXTS),
    ("suche", "wo"): ("location", _TEXT),
    ("suche", "veroeffentlichtseit"): ("published_since", _WHOLE_NUMBER),
    ("bundesagentur", "umkreis"): ("radius", _WHOLE_NUMBER),
    ("watchlist", "firmen"): ("companies", _LIST_OF_TABLES),
    ("report", "mindest_score"): ("min_score", _WHOLE_NUMBER),
    ("report", "nachfassen_ab_tag"): ("follow_up_min_days", _WHOLE_NUMBER),
    ("report", "nachfassen_bis_tag"): ("follow_up_max_days", _WHOLE_NUMBER),
}
# Felder einer Firma der Watchlist, übersetzt in `_to_company`.
_COMPANY_FIELDS = {"name": _TEXT, "ats": _TEXT, "slug": _TEXT}
# Abschnitt, in den ein deutscher Schlüssel gehört.
_SECTION_OF_KEY = {german: section for section, german in _TOML_KEYS}
_SECTIONS = set(_SECTION_OF_KEY.values())


def load_config(path: Path) -> Config:
    """Liest `config.toml`; fehlende Abschnitte und Schlüssel behalten ihren Standardwert.

    Das Laden bricht mit `ConfigError` ab, wenn ein bekannter Schlüssel nicht an seinem Platz
    steht (oben in der Datei wie im alten flachen Format oder in einem anderen Abschnitt),
    ein Abschnitt oder Schlüssel unbekannt ist oder ein Wert nicht den erwarteten Typ hat.
    Die Meldung sammelt alle Fehler der Datei und schlägt für unbekannte Namen den
    nächstliegenden bekannten vor. Fehlt die Datei, ist sie nicht lesbar oder kein gültiges
    TOML, wirft das Laden ebenfalls `ConfigError`.
    """
    raw = _read_toml(path)
    _reject_problems(raw, path)
    values = {
        english: raw[section][german]
        for (section, german), (english, _) in _TOML_KEYS.items()
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


def _reject_problems(raw: dict, path: Path) -> None:
    flat_keys = _flat_keys(raw)
    problems = [
        *flat_keys,
        *_sections_without_table(raw),
        *_keys_in_other_section(raw),
        *_companies_without_tables(raw),
        *_unknown_sections(raw),
        *_unknown_keys(raw),
        *_wrong_value_types(raw),
        *_company_field_problems(raw),
    ]
    if problems:
        hint = (
            " Das alte flache Format ohne Abschnitte wird nicht mehr gelesen." if flat_keys else ""
        )
        raise ConfigError(
            f"{path} ist ungültig: " + "; ".join(dict.fromkeys(problems)) + "." + hint
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


def _wrong_value_types(raw: dict) -> list[str]:
    # Die Firmen haben mit `_companies_without_tables` eine eigene Meldung.
    return [
        f"`[{section}] {german}` muss {_TOML_KEYS[(section, german)][1].words} sein"
        for section, german, value in _known_keys_in_sections(raw)
        if _SECTION_OF_KEY[german] == section
        and not _is_companies(section, german)
        and not _TOML_KEYS[(section, german)][1].accepts(value)
    ]


def _company_field_problems(raw: dict) -> list[str]:
    companies = raw.get("watchlist", {}).get("firmen", []) if _is_table(raw, "watchlist") else []
    if not _is_list_of_tables(companies):
        return []  # meldet `_companies_without_tables`
    place = _place("watchlist", "firmen")
    fields = {name: name for name in _COMPANY_FIELDS}
    return [
        f"`{place} {name}` unbekannt" + _suggestion(name, fields)
        if name not in _COMPANY_FIELDS
        else f"`{place} {name}` muss {_COMPANY_FIELDS[name].words} sein"
        for company in companies
        for name, value in company.items()
        if name not in _COMPANY_FIELDS or not _COMPANY_FIELDS[name].accepts(value)
    ]


def _is_table(raw: dict, section: str) -> bool:
    return isinstance(raw.get(section), dict)


def _unknown_sections(raw: dict) -> list[str]:
    # Unbekannte Tabellen oben gelten als Abschnitt, andere Werte als Schlüssel im alten
    # flachen Format; für diese wird der bekannte Schlüssel an seinem Platz vorgeschlagen.
    sections = {section: f"[{section}]" for section in _SECTIONS}
    keys = {german: _place(section, german) for section, german in _TOML_KEYS}
    return [
        f"Abschnitt `[{name}]` unbekannt" + _suggestion(name, sections)
        if isinstance(value, dict)
        else f"`{name}` unbekannt" + _suggestion(name, keys)
        for name, value in raw.items()
        if name not in _SECTIONS and name not in _SECTION_OF_KEY
    ]


def _unknown_keys(raw: dict) -> list[str]:
    return [
        f"`[{section}] {german}` unbekannt" + _suggestion(german, _keys_of(section))
        for section, table in raw.items()
        if section in _SECTIONS and isinstance(table, dict)
        for german in table
        if german not in _SECTION_OF_KEY
    ]


def _keys_of(section: str) -> dict[str, str]:
    return {german: german for known_section, german in _TOML_KEYS if known_section == section}


def _suggestion(name: str, spellings: dict[str, str]) -> str:
    """Vorschlag des nächstliegenden bekannten Namens als `spellings[name]`, falls es einen gibt."""
    closest = difflib.get_close_matches(name.lower(), list(spellings), n=1)
    return f", meintest du `{spellings[closest[0]]}`?" if closest else ""


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
    return _TOML_KEYS[(section, german)][0] == "companies"


def _to_company(entry: dict) -> WatchlistCompany:
    # Fehlt etwas, scheitert erst die Suche dieser Firma, nicht das Laden der Konfiguration.
    slug = entry.get("slug", "")
    return WatchlistCompany(name=entry.get("name", slug), ats=entry.get("ats", ""), slug=slug)
