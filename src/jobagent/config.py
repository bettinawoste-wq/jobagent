"""Konfiguration eines Laufs aus `config.toml`."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from jobagent.report import DEFAULT_MIN_SCORE
from jobagent.sources.watchlist import WatchlistCompany


@dataclass(frozen=True)
class Config:
    """Konfiguration eines Laufs; in `config.toml` stehen die Schluessel deutsch."""

    keywords: list[str] = field(default_factory=list)
    location: str | None = None
    radius: int | None = None
    published_since: int | None = None
    min_score: int = DEFAULT_MIN_SCORE
    follow_up_min_days: int = 14
    follow_up_max_days: int = 28
    companies: list[WatchlistCompany] = field(default_factory=list)


class ConfigError(Exception):
    """`config.toml` fehlt, ist kaputt, oder ein Schluessel steht nicht an seinem Platz."""


# Die einzige Stelle, an der die deutschen Schluessel aus `config.toml` uebersetzt werden:
# (Abschnitt, Schluessel) -> Feld von `Config`.
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
# Abschnitt, in den ein deutscher Schluessel gehoert.
_HOME = {german: section for section, german in _TOML_KEYS}
_SECTIONS = set(_HOME.values())


def load_config(path: Path) -> Config:
    """Liest `config.toml`; fehlende Abschnitte und Schluessel behalten ihren Standardwert.

    Steht ein bekannter Schluessel oben in der Datei wie im alten flachen Format oder in einem
    anderen bekannten Abschnitt, bricht das Laden mit `ConfigError` ab und nennt seinen Platz.
    Unbekannte Abschnitte und Schluessel werden nicht geprueft. Fehlt die Datei, ist sie
    nicht lesbar oder kein gueltiges TOML, wirft das Laden ebenfalls `ConfigError`.
    """
    raw = _read_toml(path)
    _reject_misplaced(raw)
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


def _reject_misplaced(raw: dict) -> None:
    problems = []
    for key, value in raw.items():
        if key in _HOME:
            problems.append(f"`{key}` gehört unter `{_place(_HOME[key], key)}`")
        elif key in _SECTIONS:
            if not isinstance(value, dict):
                problems.append(f"`{key}` muss ein Abschnitt `[{key}]` sein")
                continue
            for german, inner in value.items():
                home = _HOME.get(german)
                if home is None:
                    continue
                if home != key:
                    found = _written(key, german, inner)
                    problems.append(f"`{found}` gehört unter `{_place(home, german)}`")
                elif _is_companies(home, german) and not _is_list_of_tables(inner):
                    problems.append(f"`[{key}] {german}` muss als `{_place(home, german)}` stehen")
    if problems:
        flat = any(key in _HOME for key in raw)
        hint = " Das alte flache Format ohne Abschnitte wird nicht mehr gelesen." if flat else ""
        raise ConfigError(
            "config.toml ist nicht richtig gegliedert: " + "; ".join(problems) + "." + hint
        )


def _place(section: str, german: str) -> str:
    if _is_companies(section, german):
        return f"[[{section}.{german}]]"
    return f"[{section}] {german}"


def _written(section: str, german: str, value: object) -> str:
    # So, wie der Schluessel in der Datei steht.
    if value and _is_list_of_tables(value):
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
