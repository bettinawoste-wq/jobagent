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
    """`config.toml` laesst sich nicht als Konfiguration lesen."""


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


def load_config(path: Path) -> Config:
    """Liest `config.toml`; fehlende Abschnitte und Schluessel behalten ihren Standardwert.

    Steht ein Schluessel des alten flachen Formats noch oben in der Datei, bricht das Laden
    mit `ConfigError` ab und nennt seinen neuen Platz.
    """
    with path.open("rb") as file:
        raw = tomllib.load(file)
    _reject_flat_keys(raw)
    values = {
        english: raw[section][german]
        for (section, german), english in _TOML_KEYS.items()
        if german in raw.get(section, {})
    }
    if "companies" in values:
        values["companies"] = [_to_company(entry) for entry in values["companies"]]
    return Config(**values)


def _reject_flat_keys(raw: dict) -> None:
    moved = [
        f"`{german}` steht jetzt unter `{_place(section, german)}`"
        for section, german in _TOML_KEYS
        if german in raw
    ]
    if moved:
        raise ConfigError(
            "config.toml nutzt noch das alte flache Format: " + "; ".join(moved) + "."
        )


def _place(section: str, german: str) -> str:
    if german == "firmen":
        return f"[[{section}.{german}]]"
    return f"[{section}] {german}"


def _to_company(entry: dict) -> WatchlistCompany:
    # Fehlt etwas, scheitert erst die Suche dieser Firma, nicht das Laden der Konfiguration.
    slug = entry.get("slug", "")
    return WatchlistCompany(name=entry.get("name", slug), ats=entry.get("ats", ""), slug=slug)
