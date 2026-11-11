"""Eine Anzeige: eine einzelne Veröffentlichung in einer Quelle (siehe GLOSSARY.md)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobAd:
    id: str
    title: str
    company: str | None
    location: str | None
    link: str
    description: str | None = None
