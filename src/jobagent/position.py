"""Erkennt, wann mehrere Anzeigen dieselbe Stelle meinen (siehe GLOSSARY.md)."""

import re

_GENDER_NOTE = re.compile(
    r"\(\s*(?:[mwdxfi]\s*[/|,]\s*)+[mwdxfi]\s*\)"  # (m/w/d), (w/m/x)
    r"|\(\s*(?:gn|all genders|alle geschlechter)\s*\)"
    r"|\b[mwdxf]\s*/\s*[mwdxf](?:\s*/\s*[mwdxfi])*\b"  # m/w/d ohne Klammern
    r"|/-?in\b",  # Entwickler/in
    re.IGNORECASE,
)
_NON_WORD = re.compile(r"[^\w]+")
_REGISTERED_ASSOCIATION = re.compile(r"\be\.\s*v\.", re.IGNORECASE)
_LEGAL_FORMS = {
    "gmbh",
    "mbh",
    "ag",
    "se",
    "kg",
    "kgaa",
    "ohg",
    "ug",
    "gbr",
    "co",
    "haftungsbeschränkt",
    "inc",
    "ltd",
    "llc",
    "plc",
    "corp",
}


def position_key(company: str | None, title: str) -> str:
    """Bildet den Vergleichswert, an dem dieselbe Stelle erkannt wird.

    Ignoriert Schreibweise, Geschlechtsangaben im Titel, die Rechtsform der
    Firma und einen vorangestellten Firmennamen im Titel.
    """
    company_normalized = _normalized_company(company or "")
    title_normalized = _normalized_title(_without_company_prefix(title, company_normalized))
    return f"{company_normalized}|{title_normalized}"


def _without_company_prefix(title: str, company_normalized: str) -> str:
    # Die Bundesagentur liefert manche Titel als "Firma GmbH: Eigentlicher Titel".
    prefix, separator, rest = title.partition(":")
    if separator and rest.strip() and _normalized_company(prefix) == company_normalized:
        return rest
    return title


def _normalized_title(title: str) -> str:
    return " ".join(_words(_GENDER_NOTE.sub(" ", title)))


def _normalized_company(company: str) -> str:
    words = _words(_REGISTERED_ASSOCIATION.sub(" ", company))
    # Mindestens ein Wort bleibt, falls die Firma tatsaechlich so heisst.
    while len(words) > 1 and words[-1] in _LEGAL_FORMS:
        words.pop()
    return " ".join(words)


def _words(text: str) -> list[str]:
    return _NON_WORD.sub(" ", text.casefold()).split()
