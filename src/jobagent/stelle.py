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

    Ignoriert Schreibweise, Geschlechtsangaben im Titel, die Rechtsform der
    Firma und einen vorangestellten Firmennamen im Titel.
    """
    firma_normalisiert = _firma_normalisiert(firma or "")
    titel_normalisiert = _titel_normalisiert(_ohne_firmen_vorsatz(titel, firma_normalisiert))
    return f"{firma_normalisiert}|{titel_normalisiert}"


def _ohne_firmen_vorsatz(titel: str, firma_normalisiert: str) -> str:
    # Die Bundesagentur liefert manche Titel als "Firma GmbH: Eigentlicher Titel".
    vorsatz, trenner, rest = titel.partition(":")
    if trenner and rest.strip() and _firma_normalisiert(vorsatz) == firma_normalisiert:
        return rest
    return titel


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
