"""Konfiguration eines Laufs aus `config.toml`."""

import difflib
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, TypeGuard

from jobagent.report import DEFAULT_MIN_SCORE
from jobagent.score import SCORE_SCALE
from jobagent.search_window import MAX_SEARCH_WINDOW_DAYS
from jobagent.sources.watchlist import ATS_NAMES, WatchlistCompany


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


def _is_list_of_tables(value: object) -> TypeGuard[list[dict]]:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


_TEXT = _ValueType("ein Text", lambda value: isinstance(value, str))
_WHOLE_NUMBER = _ValueType("eine ganze Zahl", _is_whole_number)
_LIST_OF_TEXTS = _ValueType("eine Liste von Texten", _is_list_of_texts)
_LIST_OF_TABLES = _ValueType("eine Liste von Tabellen", _is_list_of_tables)


class _Bounds(NamedTuple):
    """Wertebereich einer ganzen Zahl; ohne `high` nach oben offen."""

    low: int
    high: int | None = None

    def accepts(self, value: int) -> bool:
        return self.low <= value and (self.high is None or value <= self.high)

    def words(self) -> str:
        if self.high is None:
            return f"mindestens {self.low} sein"
        return f"zwischen {self.low} und {self.high} liegen"


class _Key(NamedTuple):
    """Wohin ein deutscher Schlüssel übersetzt wird, welchen Typ sein Wert haben muss und,
    bei Zahlen, in welchem Bereich er liegen muss."""

    field: str
    value_type: _ValueType
    bounds: _Bounds | None = None


# Die einzige Stelle, an der die deutschen Schlüssel aus `config.toml` übersetzt werden:
# (Abschnitt, Schlüssel) -> Feld von `Config` und erwarteter Typ.
_TOML_KEYS = {
    ("suche", "was"): _Key("keywords", _LIST_OF_TEXTS),
    ("suche", "wo"): _Key("location", _TEXT),
    ("suche", "veroeffentlichtseit"): _Key(
        "published_since", _WHOLE_NUMBER, _Bounds(1, MAX_SEARCH_WINDOW_DAYS)
    ),
    ("bundesagentur", "umkreis"): _Key("radius", _WHOLE_NUMBER, _Bounds(0)),
    ("watchlist", "firmen"): _Key("companies", _LIST_OF_TABLES),
    ("report", "mindest_score"): _Key(
        "min_score", _WHOLE_NUMBER, _Bounds(SCORE_SCALE[0], SCORE_SCALE[-1])
    ),
    ("report", "nachfassen_ab_tag"): _Key("follow_up_min_days", _WHOLE_NUMBER, _Bounds(0)),
    ("report", "nachfassen_bis_tag"): _Key("follow_up_max_days", _WHOLE_NUMBER, _Bounds(0)),
}
# Platz der Firmen der Watchlist, des einzigen Eintrags, der eine Liste von Tabellen ist.
_COMPANIES_KEY = ("watchlist", "firmen")
# Felder einer Firma der Watchlist, übersetzt in `_to_company`.
_COMPANY_FIELDS = {"name": _TEXT, "ats": _TEXT, "slug": _TEXT}
# Abschnitt, in den ein deutscher Schlüssel gehört.
_SECTION_OF_KEY = {german: section for section, german in _TOML_KEYS}
_SECTIONS = set(_SECTION_OF_KEY.values())


def load_config(path: Path) -> Config:
    """Liest `config.toml`; fehlende Abschnitte und Schlüssel behalten ihren Standardwert.

    Das Laden bricht mit `ConfigError` ab, wenn ein bekannter Schlüssel nicht an seinem Platz
    steht (oben in der Datei wie im alten flachen Format oder in einem anderen Abschnitt),
    ein Abschnitt oder Schlüssel unbekannt ist, ein Wert nicht den erwarteten Typ hat oder
    außerhalb seines Wertebereichs liegt (auch `nachfassen_ab_tag` nach `nachfassen_bis_tag`
    und ein `ats` außer `ATS_NAMES`).
    Die Meldung sammelt alle Fehler der Datei und schlägt für unbekannte Namen den
    nächstliegenden bekannten vor. Fehlt die Datei, ist sie nicht lesbar oder kein gültiges
    TOML, wirft das Laden ebenfalls `ConfigError`.
    """
    raw = _read_toml(path)
    _reject_invalid(raw, path)
    values = {
        key.field: raw[section][german]
        for (section, german), key in _TOML_KEYS.items()
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


def _reject_invalid(raw: dict, path: Path) -> None:
    flat_keys = _flat_keys(raw)
    problems = [
        *flat_keys,
        *_sections_without_table(raw),
        *_keys_in_other_section(raw),
        *_unknown_top_level(raw),
        *_unknown_keys(raw),
        *_wrong_value_types(raw),
        *_values_out_of_bounds(raw),
        *_follow_up_out_of_order(raw),
        *_company_problems(raw),
    ]
    if problems:
        text = "; ".join(problems)
        # Endet die Meldung mit einem Vorschlag, schließt sie mit dessen Fragezeichen.
        end = "" if text.endswith("?") else "."
        hint = (
            " Das alte flache Format ohne Abschnitte wird nicht mehr gelesen." if flat_keys else ""
        )
        raise ConfigError(f"{path} ist ungültig: {text}{end}{hint}")


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
        for section, german, value in _keys_in_sections(raw)
        if german in _SECTION_OF_KEY and _SECTION_OF_KEY[german] != section
    ]


def _unknown_top_level(raw: dict) -> list[str]:
    return [
        _unknown_top_level_name(name, value)
        for name, value in raw.items()
        if name not in _SECTIONS and name not in _SECTION_OF_KEY
    ]


def _unknown_top_level_name(name: str, value: object) -> str:
    # Eine Tabelle oben ist ein Abschnitt; jeder andere Wert ein Schlüssel wie im alten
    # flachen Format, für den ein bekannter Schlüssel an seinem Platz vorgeschlagen wird.
    if isinstance(value, dict):
        return _unknown(f"Abschnitt `[{name}]`", _closest(name, _SECTIONS), lambda s: f"[{s}]")
    return _unknown(f"`{name}`", _closest(name, _SECTION_OF_KEY), spell=_place_of)


def _unknown_keys(raw: dict) -> list[str]:
    return [
        _unknown_key_in_section(section, german)
        for section, german, _ in _keys_in_sections(raw)
        if german not in _SECTION_OF_KEY
    ]


def _unknown_key_in_section(section: str, german: str) -> str:
    # Vorgeschlagen wird erst ein Schlüssel desselben Abschnitts, der Kürze halber ohne
    # Abschnitt, außer er steht als Liste von Tabellen; sonst einer aus einem anderen
    # Abschnitt an seinem Platz.
    label = f"`[{section}] {german}`"
    same_section = _closest(german, [key for known, key in _TOML_KEYS if known == section])
    if same_section is None:
        return _unknown(label, _closest(german, _SECTION_OF_KEY), spell=_place_of)
    if _is_companies(section, same_section):
        return _unknown(label, same_section, spell=_place_of)
    return _unknown(label, same_section, spell=str)


def _wrong_value_types(raw: dict) -> list[str]:
    return [
        _wrong_value_type(section, german)
        for section, german, value in _keys_in_sections(raw)
        if _SECTION_OF_KEY.get(german) == section
        and not _TOML_KEYS[(section, german)].value_type.accepts(value)
    ]


def _wrong_value_type(section: str, german: str) -> str:
    message = f"`[{section}] {german}` muss {_TOML_KEYS[(section, german)].value_type.words} sein"
    place = _place(section, german)
    if place != _spelling(section, german, list_of_tables=False):
        message += f", geschrieben als `{place}`"
    return message


def _values_out_of_bounds(raw: dict) -> list[str]:
    # Nur Werte vom richtigen Typ; einen falschen meldet schon `_wrong_value_types`.
    return [
        f"`[{section}] {german}` muss {bounds.words()}"
        for section, german, value in _keys_in_sections(raw)
        if _SECTION_OF_KEY.get(german) == section
        and (bounds := _TOML_KEYS[(section, german)].bounds) is not None
        and _TOML_KEYS[(section, german)].value_type.accepts(value)
        and isinstance(value, int)
        and not bounds.accepts(value)
    ]


def _follow_up_out_of_order(raw: dict) -> list[str]:
    # Ein fehlender Wert zählt mit seinem Standard; einen falschen Typ meldet schon
    # `_wrong_value_types`.
    table = raw.get("report")
    table = table if isinstance(table, dict) else {}
    start = table.get("nachfassen_ab_tag", Config.follow_up_min_days)
    end = table.get("nachfassen_bis_tag", Config.follow_up_max_days)
    if not (_is_whole_number(start) and _is_whole_number(end)) or start <= end:
        return []
    default = "" if "nachfassen_bis_tag" in table else f" (Standard {end})"
    return [
        "`[report] nachfassen_ab_tag` darf nicht größer sein als "
        f"`[report] nachfassen_bis_tag`{default}"
    ]


def _company_problems(raw: dict) -> list[str]:
    section, german = _COMPANIES_KEY
    table = raw.get(section)
    companies = table.get(german) if isinstance(table, dict) else None
    if not _is_list_of_tables(companies):
        return []  # Fehlende Firmen sind erlaubt, falsch geformte meldet `_wrong_value_types`.
    return [
        problem
        for number, company in enumerate(companies, start=1)
        for problem in _problems_of_company(number, company)
    ]


def _problems_of_company(number: int, company: dict) -> list[str]:
    place = _place(*_COMPANIES_KEY)

    def label(name: str) -> str:
        return f"`{place} {name}` (Firma {number})"

    unknown = [
        _unknown(label(name), _closest(name, _COMPANY_FIELDS), spell=str)
        for name in company
        if name not in _COMPANY_FIELDS
    ]
    wrong_types = [
        f"{label(name)} muss {_COMPANY_FIELDS[name].words} sein"
        for name, value in company.items()
        if name in _COMPANY_FIELDS and not _COMPANY_FIELDS[name].accepts(value)
    ]
    ats = company.get("ats")
    unknown_ats = (
        [_unknown_ats(label("ats"), ats)] if isinstance(ats, str) and ats not in ATS_NAMES else []
    )
    return unknown + wrong_types + unknown_ats


def _unknown_ats(label: str, ats: str) -> str:
    names = " oder ".join(f"`{name}`" for name in ATS_NAMES)
    message = f"{label} muss {names} sein"
    closest = _closest(ats, ATS_NAMES)
    return message if closest is None else f"{message}, meintest du `{closest}`?"


def _unknown(label: str, closest: str | None, spell: Callable[[str], str]) -> str:
    """Meldung für einen unbekannten Namen, mit Vorschlag, falls es einen nahen gibt."""
    if closest is None:
        return f"{label} unbekannt"
    return f"{label} unbekannt, meintest du `{spell(closest)}`?"


def _closest(name: str, known: Iterable[str]) -> str | None:
    matches = difflib.get_close_matches(name.lower(), list(known), n=1)
    return matches[0] if matches else None


def _keys_in_sections(raw: dict) -> list[tuple[str, str, object]]:
    """Alle Schlüssel in bekannten Abschnitten als (Abschnitt, Schlüssel, Wert)."""
    return [
        (section, german, value)
        for section, table in raw.items()
        if section in _SECTIONS and isinstance(table, dict)
        for german, value in table.items()
    ]


def _place_of(german: str) -> str:
    return _place(_SECTION_OF_KEY[german], german)


def _place(section: str, german: str) -> str:
    """So wird der Schlüssel an seinem Platz geschrieben."""
    return _spelling(section, german, list_of_tables=_is_companies(section, german))


def _spelling(section: str, german: str, list_of_tables: bool) -> str:
    """So steht ein Schlüssel in der Datei: als Liste von Tabellen oder im Abschnitt."""
    if list_of_tables:
        return f"[[{section}.{german}]]"
    return f"[{section}] {german}"


def _is_companies(section: str, german: str) -> bool:
    return (section, german) == _COMPANIES_KEY


def _to_company(entry: dict) -> WatchlistCompany:
    # Fehlt etwas, scheitert erst die Suche dieser Firma, nicht das Laden der Konfiguration.
    slug = entry.get("slug", "")
    return WatchlistCompany(name=entry.get("name", slug), ats=entry.get("ats", ""), slug=slug)
