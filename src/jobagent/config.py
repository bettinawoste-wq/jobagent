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


# Die einzige Stelle, an der die deutschen Schluessel aus `config.toml` uebersetzt werden.
_TOML_KEYS = {
    "was": "keywords",
    "wo": "location",
    "umkreis": "radius",
    "veroeffentlichtseit": "published_since",
    "mindest_score": "min_score",
    "nachfassen_ab_tag": "follow_up_min_days",
    "nachfassen_bis_tag": "follow_up_max_days",
    "firmen": "companies",
}


def load_config(path: Path) -> Config:
    """Liest `config.toml`; fehlende Schluessel behalten ihren Standardwert."""
    with path.open("rb") as file:
        raw = tomllib.load(file)
    values = {english: raw[german] for german, english in _TOML_KEYS.items() if german in raw}
    if "companies" in values:
        values["companies"] = [_to_company(entry) for entry in values["companies"]]
    return Config(**values)


def _to_company(entry: dict) -> WatchlistCompany:
    # Fehlt etwas, scheitert erst die Suche dieser Firma, nicht das Laden der Konfiguration.
    slug = entry.get("slug", "")
    return WatchlistCompany(name=entry.get("name", slug), ats=entry.get("ats", ""), slug=slug)
