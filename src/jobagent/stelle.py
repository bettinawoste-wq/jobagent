"""Erkennt, wann mehrere Anzeigen dieselbe Stelle meinen (siehe GLOSSARY.md)."""

import re

_GESCHLECHTSANGABE = re.compile(
    r"\(\s*(?:[mwdxfi]\s*[/|,]\s*)+[mwdxfi]\s*\)"  # (m/w/d), (w/m/x)
    r"|\(\s*(?:gn|all genders|alle geschlechter)\s*\)"
    r"|\b[mwdxf]\s*/\s*[mwdxf](?:\s*/\s*[mwdxfi])*\b"  # m/w/d ohne Klammern
    r"|/-?in\b",  # Entwickler/in
    re.IGNORECASE,
)
_KEIN_WORTZEICHEN = re.compile(r"[^\w]+")
_EINGETRAGENER_VEREIN = re.compile(r"\be\.\s*v\.", re.IGNORECASE)
_RECHTSFORMEN = {
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


def stellen_schluessel(firma: str | None, titel: str) -> str:
    """Bildet den Vergleichswert, an dem dieselbe Stelle erkannt wird.

    Ignoriert Schreibweise, Geschlechtsangaben im Titel und die Rechtsform
    der Firma.
    """
    return f"{_firma_normalisiert(firma or '')}|{_titel_normalisiert(titel)}"


def _titel_normalisiert(titel: str) -> str:
    return " ".join(_woerter(_GESCHLECHTSANGABE.sub(" ", titel)))


def _firma_normalisiert(firma: str) -> str:
    woerter = _woerter(_EINGETRAGENER_VEREIN.sub(" ", firma))
    # Mindestens ein Wort bleibt, falls die Firma tatsaechlich so heisst.
    while len(woerter) > 1 and woerter[-1] in _RECHTSFORMEN:
        woerter.pop()
    return " ".join(woerter)


def _woerter(text: str) -> list[str]:
    return _KEIN_WORTZEICHEN.sub(" ", text.casefold()).split()
