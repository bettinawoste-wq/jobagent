"""Eine Anzeige: eine einzelne Veröffentlichung in einer Quelle (siehe GLOSSARY.md)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobAd:
    id: str
    titel: str
    firma: str | None
    ort: str | None
    link: str
    beschreibung: str | None = None
