"""Tests fuer report.py mit temporaerem Ausgabeverzeichnis."""

from datetime import date, timedelta
from pathlib import Path

from jobagent.fetch import Quellenstatus
from jobagent.job_ad import JobAd
from jobagent.report import BereitsBeworben, schreibe_report
from jobagent.score import Assessment
from jobagent.store import Nachfasskandidat


def _job_ad(id_: str, titel: str) -> JobAd:
    return JobAd(
        id=id_,
        titel=titel,
        firma="Beispiel GmbH",
        ort="München",
        link=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{id_}",
    )


def _schreibe_pfad(*args, **kwargs) -> Path:
    return schreibe_report(*args, **kwargs).pfad


def _assessment(score: int, kurzfazit: str = "Passt gut.") -> Assessment:
    return Assessment(
        score=score,
        passt=["Python"],
        passt_nicht=[],
        luecken=["Kubernetes"],
        kurzfazit=kurzfazit,
    )


def test_schreibe_report_sortiert_nach_score_absteigend(tmp_path: Path) -> None:
    treffer = [
        (_job_ad("a-1", "Niedrig"), _assessment(2)),
        (_job_ad("a-2", "Hoch"), _assessment(5)),
        (_job_ad("a-3", "Mittel"), _assessment(3)),
    ]

    pfad = _schreibe_pfad(treffer, date(2026, 11, 5), ausgabe_verzeichnis=tmp_path)

    assert pfad == tmp_path / "2026-11-05.md"
    inhalt = pfad.read_text(encoding="utf-8")
    pos_hoch = inhalt.index("Hoch")
    pos_mittel = inhalt.index("Mittel")
    pos_niedrig = inhalt.index("Niedrig")
    assert pos_hoch < pos_mittel < pos_niedrig


def test_treffer_werden_in_rangfolge_ab_eins_nummeriert(tmp_path: Path) -> None:
    treffer = [
        (_job_ad("a-1", "Niedrig"), _assessment(2)),
        (_job_ad("a-2", "Hoch"), _assessment(5)),
        (_job_ad("a-3", "Mittel"), _assessment(3)),
    ]

    geschrieben = schreibe_report(treffer, date(2026, 11, 5), ausgabe_verzeichnis=tmp_path)

    inhalt = geschrieben.pfad.read_text(encoding="utf-8")
    assert "## 1. Hoch – Score 5/5" in inhalt
    assert "## 2. Mittel – Score 3/5" in inhalt
    assert "**3.** Niedrig" in inhalt
    assert geschrieben.nummern == {"a-2": 1, "a-3": 2, "a-1": 3}


def test_treffer_unter_mindest_score_werden_einzeilig(tmp_path: Path) -> None:
    treffer = [
        (_job_ad("a-1", "Niedrig"), _assessment(2, "Zu weit weg.")),
        (_job_ad("a-2", "Grenzfall"), _assessment(3)),
    ]

    pfad = _schreibe_pfad(treffer, date(2026, 11, 5), ausgabe_verzeichnis=tmp_path, mindest_score=3)

    inhalt = pfad.read_text(encoding="utf-8")
    assert "## 1. Grenzfall – Score 3/5" in inhalt
    assert "## Weitere Treffer (Score unter 3)" in inhalt
    assert (
        "- **2.** Niedrig (Beispiel GmbH, München) – Score 2/5: Zu weit weg. – "
        "https://www.arbeitsagentur.de/jobsuche/jobdetail/a-1\n"
    ) in inhalt
    assert inhalt.count("- Passt:") == 1


def test_nur_niedrige_treffer_beginnen_bei_nummer_eins(tmp_path: Path) -> None:
    treffer = [(_job_ad("a-1", "Niedrig"), _assessment(1))]

    geschrieben = schreibe_report(treffer, date(2026, 11, 5), ausgabe_verzeichnis=tmp_path)

    assert "- **1.** Niedrig" in geschrieben.pfad.read_text(encoding="utf-8")
    assert geschrieben.nummern == {"a-1": 1}


def test_ohne_niedrige_treffer_fehlt_der_kompakte_block(tmp_path: Path) -> None:
    pfad = _schreibe_pfad(
        [(_job_ad("a-1", "Niedrig"), _assessment(1))],
        date(2026, 11, 5),
        ausgabe_verzeichnis=tmp_path,
        mindest_score=1,
    )

    inhalt = pfad.read_text(encoding="utf-8")
    assert "## 1. Niedrig" in inhalt
    assert "Weitere Treffer" not in inhalt


def test_kompakte_zeile_ohne_firma_und_ort(tmp_path: Path) -> None:
    job_ad = JobAd(id="a-1", titel="Niedrig", firma=None, ort=None, link="https://x.example")

    pfad = _schreibe_pfad(
        [(job_ad, _assessment(1))], date(2026, 11, 5), ausgabe_verzeichnis=tmp_path
    )

    assert "Niedrig (unbekannt, unbekannt)" in pfad.read_text(encoding="utf-8")


def test_jeder_report_beginnt_wieder_bei_eins(tmp_path: Path) -> None:
    tag = date(2026, 11, 5)
    schreibe_report([(_job_ad("a-1", "Erster"), _assessment(4))], tag, ausgabe_verzeichnis=tmp_path)

    zweiter = schreibe_report(
        [(_job_ad("a-2", "Zweiter"), _assessment(3))], tag, ausgabe_verzeichnis=tmp_path
    )

    assert zweiter.nummern == {"a-2": 1}
    assert "## 1. Zweiter" in zweiter.pfad.read_text(encoding="utf-8")


def test_report_ohne_treffer_hat_keine_nummern(tmp_path: Path) -> None:
    geschrieben = schreibe_report([], date(2026, 11, 5), ausgabe_verzeichnis=tmp_path)

    assert geschrieben.nummern == {}


def test_schreibe_report_enthaelt_alle_pflichtfelder(tmp_path: Path) -> None:
    treffer = [(_job_ad("a-1", "Softwareentwickler"), _assessment(4, "Gute Passung."))]

    pfad = _schreibe_pfad(treffer, date(2026, 11, 5), ausgabe_verzeichnis=tmp_path)
    inhalt = pfad.read_text(encoding="utf-8")

    assert "Softwareentwickler" in inhalt
    assert "Beispiel GmbH" in inhalt
    assert "München" in inhalt
    assert "https://www.arbeitsagentur.de/jobsuche/jobdetail/a-1" in inhalt
    assert "4/5" in inhalt
    assert "Gute Passung." in inhalt
    assert "Python" in inhalt
    assert "Kubernetes" in inhalt


def test_schreibe_report_ohne_treffer_schreibt_notiz_statt_leerer_datei(tmp_path: Path) -> None:
    pfad = _schreibe_pfad([], date(2026, 11, 5), ausgabe_verzeichnis=tmp_path)

    inhalt = pfad.read_text(encoding="utf-8")
    assert "Keine neuen Treffer" in inhalt
    assert len(inhalt.strip()) > 0


def test_zweiter_lauf_am_selben_tag_ueberschreibt_ersten_report_nicht(tmp_path: Path) -> None:
    tag = date(2026, 11, 5)
    erster = _schreibe_pfad(
        [(_job_ad("a-1", "Erster Lauf"), _assessment(4))], tag, ausgabe_verzeichnis=tmp_path
    )

    zweiter = _schreibe_pfad(
        [(_job_ad("a-2", "Zweiter Lauf"), _assessment(3))], tag, ausgabe_verzeichnis=tmp_path
    )

    assert erster == tmp_path / "2026-11-05.md"
    assert zweiter == tmp_path / "2026-11-05-2.md"
    assert "Erster Lauf" in erster.read_text(encoding="utf-8")
    assert "Zweiter Lauf" in zweiter.read_text(encoding="utf-8")


def test_lauf_ohne_treffer_ueberschreibt_vorhandenen_report_nicht(tmp_path: Path) -> None:
    tag = date(2026, 11, 5)
    erster = _schreibe_pfad(
        [(_job_ad("a-1", "Erster Lauf"), _assessment(4))], tag, ausgabe_verzeichnis=tmp_path
    )

    zweiter = _schreibe_pfad([], tag, ausgabe_verzeichnis=tmp_path)

    assert zweiter != erster
    assert "Erster Lauf" in erster.read_text(encoding="utf-8")


def test_dritter_lauf_am_selben_tag_bekommt_naechste_laufnummer(tmp_path: Path) -> None:
    tag = date(2026, 11, 5)
    _schreibe_pfad([], tag, ausgabe_verzeichnis=tmp_path)
    _schreibe_pfad([], tag, ausgabe_verzeichnis=tmp_path)

    dritter = _schreibe_pfad([], tag, ausgabe_verzeichnis=tmp_path)

    assert dritter == tmp_path / "2026-11-05-3.md"


def test_quellenstatus_steht_vor_den_treffern(tmp_path: Path) -> None:
    quellen = [Quellenstatus("Arbeitnow", 3, []), Quellenstatus("Bundesagentur", 1, [])]

    pfad = _schreibe_pfad(
        [(_job_ad("a-1", "Stelle"), _assessment(4))],
        date(2026, 11, 5),
        ausgabe_verzeichnis=tmp_path,
        quellen=quellen,
    )

    inhalt = pfad.read_text(encoding="utf-8")
    assert "- Arbeitnow: 3 Anzeigen" in inhalt
    assert "- Bundesagentur: 1 Anzeige\n" in inhalt
    assert inhalt.index("Arbeitnow") < inhalt.index("## 1. Stelle")


def test_quellenstatus_nennt_fehler_auch_bei_teilergebnis(tmp_path: Path) -> None:
    quellen = [Quellenstatus("Arbeitnow", 2, ["Data Scientist: HTTP 500", "IT: HTTP 503"])]

    pfad = _schreibe_pfad([], date(2026, 11, 5), ausgabe_verzeichnis=tmp_path, quellen=quellen)

    assert "- Arbeitnow: FEHLER, 2 Anzeigen (Data Scientist: HTTP 500; IT: HTTP 503)" in (
        pfad.read_text(encoding="utf-8")
    )


def test_ohne_treffer_steht_quellenausfall_trotzdem_im_report(tmp_path: Path) -> None:
    quellen = [Quellenstatus("Arbeitnow", 0, ["IT: keine Verbindung"])]

    pfad = _schreibe_pfad([], date(2026, 11, 5), ausgabe_verzeichnis=tmp_path, quellen=quellen)

    inhalt = pfad.read_text(encoding="utf-8")
    assert "FEHLER" in inhalt
    assert "Keine neuen Treffer" in inhalt


_ABSAGE = BereitsBeworben("absage", date(2026, 10, 1), "Text identisch")


def test_bereits_beworben_steht_im_eigenen_block_am_ende(tmp_path: Path) -> None:
    treffer = [
        (_job_ad("a-1", "Beworben"), _assessment(5)),
        (_job_ad("a-2", "Offen"), _assessment(4)),
    ]

    pfad = _schreibe_pfad(
        treffer,
        date(2026, 11, 5),
        ausgabe_verzeichnis=tmp_path,
        bewerbungen={"a-1": _ABSAGE},
    )

    inhalt = pfad.read_text(encoding="utf-8")
    assert "## 1. Offen" in inhalt
    assert "## Bereits beworben\n" in inhalt
    assert (
        "- **2.** Beworben (Beispiel GmbH, München) – Score 5/5 – absage, beworben am "
        "01.10.2026 – Text identisch – https://www.arbeitsagentur.de/jobsuche/jobdetail/a-1\n"
    ) in inhalt
    assert inhalt.index("## 1. Offen") < inhalt.index("## Bereits beworben")
    assert "## 2. Beworben" not in inhalt


def test_nummern_laufen_ueber_alle_bloecke(tmp_path: Path) -> None:
    treffer = [
        (_job_ad("a-1", "Beworben"), _assessment(5)),
        (_job_ad("a-2", "Voll"), _assessment(4)),
        (_job_ad("a-3", "Kompakt"), _assessment(1)),
    ]

    geschrieben = schreibe_report(
        treffer,
        date(2026, 11, 5),
        ausgabe_verzeichnis=tmp_path,
        bewerbungen={"a-1": _ABSAGE},
    )

    assert geschrieben.nummern == {"a-2": 1, "a-3": 2, "a-1": 3}
    inhalt = geschrieben.pfad.read_text(encoding="utf-8")
    assert inhalt.index("Weitere Treffer") < inhalt.index("Bereits beworben")


def test_ohne_bewerbungen_fehlt_der_block(tmp_path: Path) -> None:
    pfad = _schreibe_pfad(
        [(_job_ad("a-1", "Offen"), _assessment(4))],
        date(2026, 11, 5),
        ausgabe_verzeichnis=tmp_path,
    )

    assert "Bereits beworben" not in pfad.read_text(encoding="utf-8")


def test_nur_bereits_beworbene_treffer(tmp_path: Path) -> None:
    geschrieben = schreibe_report(
        [(_job_ad("a-1", "Beworben"), _assessment(2))],
        date(2026, 11, 5),
        ausgabe_verzeichnis=tmp_path,
        bewerbungen={"a-1": _ABSAGE},
    )

    inhalt = geschrieben.pfad.read_text(encoding="utf-8")
    assert "- **1.** Beworben" in inhalt
    assert "Weitere Treffer" not in inhalt
    assert geschrieben.nummern == {"a-1": 1}


def test_schreibe_report_erstellt_ausgabeverzeichnis(tmp_path: Path) -> None:
    ziel = tmp_path / "noch_nicht_vorhanden"

    _schreibe_pfad([], date(2026, 11, 5), ausgabe_verzeichnis=ziel)

    assert ziel.is_dir()


def _nachfassen(firma: str | None = "Firma X", vor_tagen: int = 14) -> Nachfasskandidat:
    tag = date(2026, 11, 20) - timedelta(days=vor_tagen)
    return Nachfasskandidat(firma=firma, titel="Data Engineer", beworben_am=tag)


def test_nachfass_hinweis_steht_nach_quellen_und_vor_treffern(tmp_path: Path) -> None:
    pfad = _schreibe_pfad(
        [(_job_ad("a-1", "Stelle"), _assessment(4))],
        date(2026, 11, 20),
        ausgabe_verzeichnis=tmp_path,
        quellen=[Quellenstatus("Arbeitnow", 0, [])],
        nachfassen=[_nachfassen()],
    )

    inhalt = pfad.read_text(encoding="utf-8")
    assert "## Nachfassen\n" in inhalt
    assert (
        "- Data Engineer (Firma X): seit 14 Tagen keine Antwort, nachhaken? "
        "(beworben am 06.11.2026)\n"
    ) in inhalt
    assert inhalt.index("## Quellen") < inhalt.index("## Nachfassen") < inhalt.index("## 1. Stelle")


def test_nachfass_hinweis_erscheint_auch_ohne_treffer(tmp_path: Path) -> None:
    pfad = _schreibe_pfad(
        [], date(2026, 11, 20), ausgabe_verzeichnis=tmp_path, nachfassen=[_nachfassen()]
    )

    inhalt = pfad.read_text(encoding="utf-8")
    assert "## Nachfassen" in inhalt
    assert "Keine neuen Treffer" in inhalt


def test_ohne_kandidaten_fehlt_der_nachfass_block(tmp_path: Path) -> None:
    pfad = _schreibe_pfad([], date(2026, 11, 20), ausgabe_verzeichnis=tmp_path)

    assert "Nachfassen" not in pfad.read_text(encoding="utf-8")


def test_nachfass_hinweis_ohne_firma_und_mit_einem_tag(tmp_path: Path) -> None:
    pfad = _schreibe_pfad(
        [],
        date(2026, 11, 20),
        ausgabe_verzeichnis=tmp_path,
        nachfassen=[_nachfassen(firma=None, vor_tagen=1)],
    )

    assert "Data Engineer (unbekannt): seit 1 Tag keine Antwort" in pfad.read_text(encoding="utf-8")


def test_hinweis_auf_profil_vorschlag_steht_nach_nachfassen(tmp_path: Path) -> None:
    pfad = _schreibe_pfad(
        [],
        date(2026, 11, 20),
        ausgabe_verzeichnis=tmp_path,
        nachfassen=[_nachfassen()],
        offenes_feedback=5,
    )

    inhalt = pfad.read_text(encoding="utf-8")
    assert (
        "## Profil-Vorschlag\n- 5 Rückmeldungen warten auf Auswertung: "
        "`python -m jobagent.profilvorschlag`\n"
    ) in inhalt
    assert inhalt.index("## Nachfassen") < inhalt.index("## Profil-Vorschlag")


def test_ohne_offenes_feedback_kein_hinweis(tmp_path: Path) -> None:
    pfad = _schreibe_pfad([], date(2026, 11, 20), ausgabe_verzeichnis=tmp_path)

    assert "Profil-Vorschlag" not in pfad.read_text(encoding="utf-8")
