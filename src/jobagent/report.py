"""Schreibt output/YYYY-MM-DD.md, sortiert nach Score."""

from datetime import date
from pathlib import Path

from jobagent.fetch import Anzeige
from jobagent.score import Bewertung

OUTPUT_DIR = Path("output")

Treffer = tuple[Anzeige, Bewertung]


def schreibe_report(
    treffer: list[Treffer],
    datum: date,
    ausgabe_verzeichnis: Path = OUTPUT_DIR,
) -> Path:
    """Schreibt die Treffer sortiert nach Score in output/YYYY-MM-DD.md.

    Ohne Treffer wird eine kurze Notiz statt einer leeren Datei erzeugt.
    Ein vorhandener Report wird nie ueberschrieben, siehe _freier_pfad.
    """
    ausgabe_verzeichnis.mkdir(parents=True, exist_ok=True)
    pfad = _freier_pfad(ausgabe_verzeichnis, datum)

    if not treffer:
        pfad.write_text(
            f"# Stellenvorschläge {datum.isoformat()}\n\nKeine neuen Treffer heute.\n",
            encoding="utf-8",
        )
        return pfad

    sortiert = sorted(treffer, key=lambda paar: paar[1].score, reverse=True)

    inhalt = f"# Stellenvorschläge {datum.isoformat()}\n\n"
    inhalt += "\n".join(_abschnitt(anzeige, bewertung) for anzeige, bewertung in sortiert)

    pfad.write_text(inhalt, encoding="utf-8")
    return pfad


def _freier_pfad(ausgabe_verzeichnis: Path, datum: date) -> Path:
    # Gesehene Anzeigen kommen nie wieder, ein ueberschriebener Report waere
    # also endgueltig verloren. Weitere Laeufe am selben Tag bekommen -2, -3, ...
    pfad = ausgabe_verzeichnis / f"{datum.isoformat()}.md"
    laufnummer = 2
    while pfad.exists():
        pfad = ausgabe_verzeichnis / f"{datum.isoformat()}-{laufnummer}.md"
        laufnummer += 1
    return pfad


def _abschnitt(anzeige: Anzeige, bewertung: Bewertung) -> str:
    zeilen = [
        f"## {anzeige.titel} – Score {bewertung.score}/5",
        f"- Firma: {anzeige.firma or 'unbekannt'}",
        f"- Ort: {anzeige.ort or 'unbekannt'}",
        f"- Link: {anzeige.link}",
        f"- Kurzfazit: {bewertung.kurzfazit}",
    ]
    if bewertung.passt:
        zeilen.append(f"- Passt: {', '.join(bewertung.passt)}")
    if bewertung.passt_nicht:
        zeilen.append(f"- Passt nicht: {', '.join(bewertung.passt_nicht)}")
    if bewertung.luecken:
        zeilen.append(f"- Lücken: {', '.join(bewertung.luecken)}")
    zeilen.append("")
    return "\n".join(zeilen)
