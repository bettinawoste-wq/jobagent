"""Schreibt output/YYYY-MM-DD.md, sortiert nach Score."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jobagent.fetch import Anzeige, Quellenstatus
from jobagent.score import Bewertung

OUTPUT_DIR = Path("output")

Treffer = tuple[Anzeige, Bewertung]


@dataclass(frozen=True, slots=True)
class GeschriebenerReport:
    pfad: Path
    nummern: dict[str, int]  # Anzeigen-ID -> Treffernummer


def schreibe_report(
    treffer: list[Treffer],
    datum: date,
    ausgabe_verzeichnis: Path = OUTPUT_DIR,
    quellen: Sequence[Quellenstatus] = (),
) -> GeschriebenerReport:
    """Schreibt die Treffer sortiert nach Score und nummeriert in output/YYYY-MM-DD.md.

    Ohne Treffer wird eine kurze Notiz statt einer leeren Datei erzeugt.
    Ein vorhandener Report wird nie ueberschrieben, siehe _freier_pfad.
    """
    ausgabe_verzeichnis.mkdir(parents=True, exist_ok=True)
    pfad = _freier_pfad(ausgabe_verzeichnis, datum)
    kopf = f"# Stellenvorschläge {datum.isoformat()}\n\n{_quellen_block(quellen)}"

    if not treffer:
        pfad.write_text(f"{kopf}Keine neuen Treffer heute.\n", encoding="utf-8")
        return GeschriebenerReport(pfad, {})

    sortiert = sorted(treffer, key=lambda paar: paar[1].score, reverse=True)
    nummeriert = list(enumerate(sortiert, start=1))

    inhalt = kopf + "\n".join(
        _abschnitt(nummer, anzeige, bewertung) for nummer, (anzeige, bewertung) in nummeriert
    )

    pfad.write_text(inhalt, encoding="utf-8")
    return GeschriebenerReport(pfad, {anzeige.id: nummer for nummer, (anzeige, _) in nummeriert})


def _freier_pfad(ausgabe_verzeichnis: Path, datum: date) -> Path:
    # Gesehene Anzeigen kommen nie wieder, ein ueberschriebener Report waere
    # also endgueltig verloren. Weitere Laeufe am selben Tag bekommen -2, -3, ...
    pfad = ausgabe_verzeichnis / f"{datum.isoformat()}.md"
    laufnummer = 2
    while pfad.exists():
        pfad = ausgabe_verzeichnis / f"{datum.isoformat()}-{laufnummer}.md"
        laufnummer += 1
    return pfad


def _quellen_block(quellen: Sequence[Quellenstatus]) -> str:
    if not quellen:
        return ""
    zeilen = "\n".join(_quellen_zeile(quelle) for quelle in quellen)
    return f"## Quellen\n{zeilen}\n\n"


def _quellen_zeile(quelle: Quellenstatus) -> str:
    anzahl = "1 Anzeige" if quelle.anzahl == 1 else f"{quelle.anzahl} Anzeigen"
    if not quelle.fehler:
        return f"- {quelle.name}: {anzahl}"
    return f"- {quelle.name}: FEHLER, {anzahl} ({'; '.join(quelle.fehler)})"


def _abschnitt(nummer: int, anzeige: Anzeige, bewertung: Bewertung) -> str:
    zeilen = [
        f"## {nummer}. {anzeige.titel} – Score {bewertung.score}/5",
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
