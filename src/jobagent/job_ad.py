"""Eine Anzeige: eine einzelne Veröffentlichung in einer Quelle (siehe GLOSSARY.md)."""

from dataclasses import dataclass, fields

from jobagent.text import encodable


@dataclass(frozen=True, slots=True)
class JobAd:
    id: str
    title: str
    company: str | None
    location: str | None
    link: str
    description: str | None = None

    def __post_init__(self) -> None:
        # Ein einzelnes Surrogat (etwa ein halbes Emoji aus einer Quelle) lässt sich nicht
        # als UTF-8 schreiben. Ohne Bereinigung scheiterten Merken, Hash und Report, und
        # die Anzeige käme in jedem Lauf wieder; so wird es zu "?".
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, str):
                object.__setattr__(self, field.name, encodable(value))
