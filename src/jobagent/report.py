"""Schreibt output/YYYY-MM-DD.md, sortiert nach Score."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jobagent.fetch import Anzeige, Quellenstatus
from jobagent.score import Bewertung
from jobagent.store import Nachfasskandidat

OUTPUT_DIR = Path("output")
STANDARD_MINDEST_SCORE = 3

Treffer = tuple[Anzeige, Bewertung]


@dataclass(frozen=True, slots=True)
class GeschriebenerReport:
    pfad: Path
    nummern: dict[str, int]  # Anzeigen-ID -> Treffernummer


@dataclass(frozen=True, slots=True)
class BereitsBeworben:
    status: str
    beworben_am: date
    textvergleich: str


def schreibe_report(
    treffer: list[Treffer],
    datum: date,
    ausgabe_verzeichnis: Path = OUTPUT_DIR,
    quellen: Sequence[Quellenstatus] = (),
    mindest_score: int = STANDARD_MINDEST_SCORE,
    bewerbungen: Mapping[str, BereitsBeworben] | None = None,
    nachfassen: Sequence[Nachfasskandidat] = (),
    offenes_feedback: int = 0,
) -> GeschriebenerReport:
    """Schreibt die Treffer sortiert nach Score und nummeriert in output/YYYY-MM-DD.md.

    Ohne Treffer wird eine kurze Notiz statt einer leeren Datei erzeugt.
    Ein vorhandener Report wird nie ueberschrieben, siehe _freier_pfad.
    """
    ausgabe_verzeichnis.mkdir(parents=True, exist_ok=True)
    pfad = _freier_pfad(ausgabe_verzeichnis, datum)
    kopf = (
        f"# Stellenvorschläge {datum.isoformat()}\n\n"
        f"{_quellen_block(quellen)}{_nachfass_block(nachfassen, datum)}"
        f"{_profil_hinweis(offenes_feedback)}"
    )

    if not treffer:
        pfad.write_text(f"{kopf}Keine neuen Treffer heute.\n", encoding="utf-8")
        return GeschriebenerReport(pfad, {})

    sortiert = sorted(treffer, key=lambda paar: paar[1].score, reverse=True)
    bewerbungen = bewerbungen or {}
    offen = [eintrag for eintrag in sortiert if eintrag[0].id not in bewerbungen]
    beworben = [eintrag for eintrag in sortiert if eintrag[0].id in bewerbungen]
    nummeriert = list(enumerate(offen + beworben, start=1))

    nummeriert_offen = nummeriert[: len(offen)]
    voll = [eintrag for eintrag in nummeriert_offen if eintrag[1][1].score >= mindest_score]
    kompakt = [eintrag for eintrag in nummeriert_offen if eintrag[1][1].score < mindest_score]

    teile = [_abschnitt(nummer, anzeige, bewertung) for nummer, (anzeige, bewertung) in voll]
    if kompakt:
        teile.append(_kompakter_block(kompakt, mindest_score))
    if beworben:
        teile.append(_beworben_block(nummeriert[len(offen) :], bewerbungen))

    inhalt = kopf + "\n".join(teile)
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


def _profil_hinweis(offenes_feedback: int) -> str:
    if not offenes_feedback:
        return ""
    return (
        f"## Profil-Vorschlag\n- {offenes_feedback} Rückmeldungen warten auf Auswertung: "
        "`python -m jobagent.profilvorschlag`\n\n"
    )


def _nachfass_block(nachfassen: Sequence[Nachfasskandidat], heute: date) -> str:
    if not nachfassen:
        return ""
    zeilen = "\n".join(_nachfass_zeile(kandidat, heute) for kandidat in nachfassen)
    return f"## Nachfassen\n{zeilen}\n\n"


def _nachfass_zeile(kandidat: Nachfasskandidat, heute: date) -> str:
    tage = (heute - kandidat.beworben_am).days
    dauer = "1 Tag" if tage == 1 else f"{tage} Tagen"
    return (
        f"- {kandidat.titel} ({kandidat.firma or 'unbekannt'}): seit {dauer} keine Antwort, "
        f"nachhaken? (beworben am {kandidat.beworben_am:%d.%m.%Y})"
    )


def _kompakter_block(kompakt: list[tuple[int, Treffer]], mindest_score: int) -> str:
    zeilen = "\n".join(
        _kompakte_zeile(nummer, anzeige, bewertung) for nummer, (anzeige, bewertung) in kompakt
    )
    return f"## Weitere Treffer (Score unter {mindest_score})\n{zeilen}\n"


def _kompakte_zeile(nummer: int, anzeige: Anzeige, bewertung: Bewertung) -> str:
    return (
        f"{_zeilenanfang(nummer, anzeige)} – "
        f"Score {bewertung.score}/5: {bewertung.kurzfazit} – {anzeige.link}"
    )


def _beworben_block(
    nummeriert: list[tuple[int, Treffer]], bewerbungen: Mapping[str, BereitsBeworben]
) -> str:
    zeilen = "\n".join(
        _beworben_zeile(nummer, anzeige, bewertung, bewerbungen[anzeige.id])
        for nummer, (anzeige, bewertung) in nummeriert
    )
    return f"## Bereits beworben\n{zeilen}\n"


def _beworben_zeile(
    nummer: int, anzeige: Anzeige, bewertung: Bewertung, bewerbung: BereitsBeworben
) -> str:
    return (
        f"{_zeilenanfang(nummer, anzeige)} – Score {bewertung.score}/5 – "
        f"{bewerbung.status}, beworben am {bewerbung.beworben_am:%d.%m.%Y} – "
        f"{bewerbung.textvergleich} – {anzeige.link}"
    )


def _zeilenanfang(nummer: int, anzeige: Anzeige) -> str:
    firma = anzeige.firma or "unbekannt"
    ort = anzeige.ort or "unbekannt"
    return f"- **{nummer}.** {anzeige.titel} ({firma}, {ort})"


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
