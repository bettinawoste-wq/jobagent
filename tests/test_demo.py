"""Tests fuer den Demo-Lauf (`--demo`), beobachtet ueber stdout und Dateien."""

import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

from jobagent import main, score


@pytest.fixture
def leeres_projekt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Frischer Clone: kein API-Key, keine profile.md, keine config.toml, kein Netz, kein Modell."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def kein_netz(*args: object, **kwargs: object) -> None:
        raise AssertionError("Demo-Lauf darf nicht ins Netz")

    def kein_modell(*args: object, **kwargs: object) -> None:
        raise AssertionError("Demo-Lauf darf kein Modell fragen")

    monkeypatch.setattr(httpx.Client, "send", kein_netz)
    monkeypatch.setattr(score, "score_job_ad", kein_modell)
    return tmp_path


def _demo_lauf(capsys: pytest.CaptureFixture[str], *argumente: str) -> str:
    main.cli(["--demo", *argumente])
    return capsys.readouterr().out


def test_demo_lauf_gibt_report_aus_ohne_etwas_anzulegen(
    leeres_projekt: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ausgabe = _demo_lauf(capsys)

    assert ausgabe.startswith("# Stellenvorschläge ")
    assert list(leeres_projekt.iterdir()) == []


def test_demo_lauf_zeigt_scores_von_1_bis_5(
    leeres_projekt: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ausgabe = _demo_lauf(capsys)

    for score_wert in range(1, 6):
        assert f"Score {score_wert}/5" in ausgabe


def test_demo_lauf_zeigt_schwache_treffer_einzeilig(
    leeres_projekt: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ausgabe = _demo_lauf(capsys)

    kompakt = ausgabe.split("## Weitere Treffer (Score unter 3)\n")[1]
    assert "SAP-Berater FI/CO (m/w/d) (Musterfirma Beratung GmbH, Beispielstadt)" in kompakt
    assert "Score 1/5" in kompakt


def test_demo_lauf_meldet_ausgefallene_quelle_und_laeuft_weiter(
    leeres_projekt: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ausgabe = _demo_lauf(capsys)

    assert (
        "- Firmen-Watchlist (Demo): FEHLER, 2 Anzeigen (Musterwerk AG: Board nicht erreichbar)"
        in ausgabe
    )
    assert "- Bundesagentur für Arbeit (Demo): 3 Anzeigen" in ausgabe


def test_demo_lauf_zeigt_nachfass_hinweis(
    leeres_projekt: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ausgabe = _demo_lauf(capsys)

    assert "## Nachfassen\n" in ausgabe
    assert "seit 18 Tagen keine Antwort, nachhaken?" in ausgabe


def test_demo_run_detects_applied_position_whose_text_differs(
    leeres_projekt: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ausgabe = _demo_lauf(capsys)

    beworben = ausgabe.split("## Bereits beworben\n")[1]
    assert "Python Developer (w/m/d) (Beispiel Tech, Remote)" in beworben
    assert "gespräch, beworben am" in beworben
    assert "Text weicht von deiner Bewerbung ab" in beworben


def test_demo_lauf_schreibt_mit_ausgabe_zusaetzlich_eine_datei(
    leeres_projekt: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ausgabe = _demo_lauf(capsys, "--ausgabe", "demo-report")

    dateien = list((leeres_projekt / "demo-report").iterdir())
    assert len(dateien) == 1
    assert dateien[0].read_text(encoding="utf-8") == ausgabe
    assert [eintrag.name for eintrag in leeres_projekt.iterdir()] == ["demo-report"]


def test_ausgabe_gibt_es_nur_im_demo_lauf(leeres_projekt: Path) -> None:
    with pytest.raises(SystemExit):
        main.cli(["--ausgabe", "demo-report"])


def _demo_lauf_am(
    tag: date, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> str:
    class Datum(date):
        @classmethod
        def today(cls) -> date:
            return tag

    monkeypatch.setattr(main, "date", Datum)
    return _demo_lauf(capsys)


def _ohne_datumsangaben(text: str) -> str:
    return re.sub(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}", "<datum>", text)


def test_demo_lauf_ist_an_jedem_tag_gleich_bis_auf_datumsangaben(
    leeres_projekt: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    im_winter = _demo_lauf_am(date(2026, 1, 5), capsys, monkeypatch)
    im_sommer = _demo_lauf_am(date(2027, 7, 31), capsys, monkeypatch)

    assert "2026-01-05" in im_winter
    assert "2027-07-31" in im_sommer
    assert _ohne_datumsangaben(im_winter) == _ohne_datumsangaben(im_sommer)


def test_demo_lauf_verlinkt_nur_auf_example_com(
    leeres_projekt: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ausgabe = _demo_lauf(capsys)

    links = re.findall(r"https?://\S+", ausgabe)
    assert len(links) == 8
    assert all(link.startswith("https://example.com/") for link in links)


def test_demo_lauf_gibt_umlaute_als_utf8_aus(tmp_path: Path) -> None:
    # Eigener Prozess ohne UTF-8-Vorgaben, so wie die Windows-Konsole ihn startet.
    umgebung = {
        name: wert
        for name, wert in os.environ.items()
        if name not in {"PYTHONIOENCODING", "PYTHONUTF8", "ANTHROPIC_API_KEY"}
    }
    umgebung["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    ergebnis = subprocess.run(
        [sys.executable, "-m", "jobagent.main", "--demo"],
        cwd=tmp_path,
        env=umgebung,
        capture_output=True,
        check=True,
    )

    assert "# Stellenvorschläge" in ergebnis.stdout.decode("utf-8")
    assert list(tmp_path.iterdir()) == []
