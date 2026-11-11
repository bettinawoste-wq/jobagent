"""Tests fuer den Profil-Vorschlag, die Anthropic-API ist vollstaendig gemockt."""

import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

from jobagent import profilvorschlag, store
from jobagent.job_ad import JobAd
from jobagent.profilvorschlag import Aenderung, erstelle_vorschlag, wende_an
from jobagent.score import Assessment

_PROFIL = "# Suchprofil\n\n## Ausschlüsse\n- Zeitarbeit: maximal Score 2\n"
_JETZT = datetime(2026, 11, 8, 15, 1, 2)
_AENDERUNG = {
    "alt": "- Zeitarbeit: maximal Score 2",
    "neu": "- Zeitarbeit: maximal Score 2 (Beratungsfirmen zählen nicht)",
    "grund": "Mehrfach falsch eingeordnet",
}


class _FakeClient:
    def __init__(self, antwort: object) -> None:
        self.antwort = antwort
        self.aufrufe: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: object) -> object:
        self.aufrufe.append(kwargs)
        if isinstance(self.antwort, Exception):
            raise self.antwort
        return self.antwort


def _antwort(daten: object, stop_reason: str = "end_turn") -> SimpleNamespace:
    text = daten if isinstance(daten, str) else json.dumps(daten, ensure_ascii=False)
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=text)],
    )


def _vorschlag(aenderungen: list[dict] | None = None, modellfehler: list[str] | None = None):
    return _antwort(
        {
            "aenderungen": [_AENDERUNG] if aenderungen is None else aenderungen,
            "modellfehler": modellfehler or [],
        }
    )


def _api_fehler() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]


@pytest.fixture
def projekt(tmp_path: Path) -> dict[str, Path]:
    db = tmp_path / "jobagent.db"
    profil = tmp_path / "profile.md"
    profil.write_text(_PROFIL, encoding="utf-8")
    _feedback_anlegen(db, "a-1")
    return {"db_pfad": db, "profil_pfad": profil}


def _feedback_anlegen(db: Path, anzeige_id: str) -> None:
    assessment = Assessment(
        score=2, passt=["Python"], passt_nicht=["Zeitarbeit"], luecken=[], kurzfazit="Eher nein."
    )
    job_ad = JobAd(id=anzeige_id, titel="Consultant", firma="KPMG AG", ort="M", link="l")
    conn = store.connect(db)
    store.mark_seen(conn, job_ad, assessment, date(2026, 11, 8))
    store.speichere_feedback(conn, anzeige_id, 3, "KPMG ist keine Zeitarbeit", date(2026, 11, 8))
    conn.close()


def _lauf(projekt: dict[str, Path], client: _FakeClient, antwort: str | Exception = "j") -> int:
    def eingabe(_: str) -> str:
        if isinstance(antwort, Exception):
            raise antwort
        return antwort

    return profilvorschlag.main(**projekt, client=client, eingabe=eingabe, jetzt=_JETZT)


def _verarbeitet(projekt: dict[str, Path]) -> list[int]:
    conn = store.connect(projekt["db_pfad"])
    try:
        return [z[0] for z in conn.execute("SELECT verarbeitet FROM feedback ORDER BY anzeige_id")]
    finally:
        conn.close()


def _sicherungen(projekt: dict[str, Path]) -> list[Path]:
    return list(projekt["profil_pfad"].parent.glob("profile.sicherung-*.md"))


def _aenderung(alt: str, neu: str) -> Aenderung:
    return Aenderung(alt=alt, neu=neu, grund="g")


def _rueckmeldung() -> store.Rueckmeldung:
    return store.Rueckmeldung(
        anzeige_id="a-1",
        titel="Consultant",
        firma="KPMG AG",
        modell_score=2,
        bewertung={"passt_nicht": ["Zeitarbeit"]},
        eigener_score=3,
        grund="KPMG ist keine Zeitarbeit",
    )


def test_wende_an_ersetzt_genau_den_auszug() -> None:
    neu, uebersprungen = wende_an("a\nb\nc\n", [_aenderung("b", "B")])

    assert neu == "a\nB\nc\n"
    assert uebersprungen == []


def test_wende_an_ueberspringt_nicht_gefundenen_auszug() -> None:
    aenderung = _aenderung("fehlt", "x")

    assert wende_an("a\n", [aenderung]) == ("a\n", [aenderung])


def test_wende_an_ueberspringt_mehrdeutigen_auszug() -> None:
    aenderung = _aenderung("a", "x")

    assert wende_an("a a\n", [aenderung]) == ("a a\n", [aenderung])


def test_wende_an_leerer_auszug_wird_uebersprungen() -> None:
    aenderung = _aenderung("", "x")

    assert wende_an("a\n", [aenderung]) == ("a\n", [aenderung])


def test_wende_an_mehrere_aenderungen_nacheinander() -> None:
    neu, _ = wende_an("a\nb\n", [_aenderung("a", "A"), _aenderung("b", "B")])

    assert neu == "A\nB\n"


def test_vorschlag_nutzt_sonnet_mit_strukturierter_ausgabe() -> None:
    client = _FakeClient(_vorschlag())

    erstelle_vorschlag(_PROFIL, [_rueckmeldung()], client=client)

    aufruf = client.aufrufe[0]
    assert aufruf["model"] == "claude-sonnet-5-5"
    assert "tool_choice" not in aufruf
    assert aufruf["output_config"]["format"]["type"] == "json_schema"
    assert aufruf["fallbacks"] == "default"
    assert aufruf["betas"] == ["server-side-fallback-2026-07-01"]


def test_vorschlag_schickt_profil_und_rueckmeldungen() -> None:
    client = _FakeClient(_vorschlag())

    erstelle_vorschlag(_PROFIL, [_rueckmeldung()], client=client)

    text = client.aufrufe[0]["messages"][0]["content"]
    assert _PROFIL in text
    assert "KPMG ist keine Zeitarbeit" in text
    assert '"modell_score": 2' in text
    assert '"eigener_score": 3' in text
    assert "Zeitarbeit" in text


def test_vorschlag_wird_gelesen() -> None:
    client = _FakeClient(_vorschlag(modellfehler=["KPMG falsch gelesen"]))

    vorschlag = erstelle_vorschlag(_PROFIL, [_rueckmeldung()], client=client)

    assert vorschlag is not None
    assert vorschlag.aenderungen == [Aenderung(**_AENDERUNG)]
    assert vorschlag.modellfehler == ["KPMG falsch gelesen"]


@pytest.mark.parametrize(
    "antwort",
    [
        _api_fehler(),
        TypeError("Could not resolve authentication method."),
        _antwort({"modellfehler": []}),
        _antwort("kein json"),
        _antwort({"aenderungen": [], "modellfehler": []}, stop_reason="refusal"),
        _antwort({"aenderungen": [], "modellfehler": []}, stop_reason="max_tokens"),
        SimpleNamespace(stop_reason="end_turn", content=[]),
    ],
)
def test_vorschlag_gibt_none_bei_fehlern(antwort: object) -> None:
    assert erstelle_vorschlag(_PROFIL, [_rueckmeldung()], client=_FakeClient(antwort)) is None


def test_uebernehmen_aendert_profil_sichert_und_verarbeitet(
    projekt: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    assert _lauf(projekt, _FakeClient(_vorschlag()), "j") == 0

    assert "Beratungsfirmen" in projekt["profil_pfad"].read_text(encoding="utf-8")
    sicherung = projekt["profil_pfad"].parent / "profile.sicherung-2026-11-08-150102.md"
    assert sicherung.read_text(encoding="utf-8") == _PROFIL
    assert _verarbeitet(projekt) == [1]
    ausgabe = capsys.readouterr().out
    assert "-- Zeitarbeit: maximal Score 2\n" in ausgabe
    assert "Mehrfach falsch eingeordnet" in ausgabe


def test_ablehnen_laesst_profil_und_verarbeitet(projekt: dict[str, Path]) -> None:
    assert _lauf(projekt, _FakeClient(_vorschlag()), "n") == 0

    assert projekt["profil_pfad"].read_text(encoding="utf-8") == _PROFIL
    assert _sicherungen(projekt) == []
    assert _verarbeitet(projekt) == [1]


@pytest.mark.parametrize("antwort", ["a", "", "vielleicht", EOFError()])
def test_abbrechen_aendert_nichts(projekt: dict[str, Path], antwort: str | Exception) -> None:
    assert _lauf(projekt, _FakeClient(_vorschlag()), antwort) == 0

    assert projekt["profil_pfad"].read_text(encoding="utf-8") == _PROFIL
    assert _sicherungen(projekt) == []
    assert _verarbeitet(projekt) == [0]


def test_nur_modellfehler_aendert_profil_nicht_und_fragt_nicht(
    projekt: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    client = _FakeClient(_vorschlag(aenderungen=[], modellfehler=["KPMG falsch gelesen"]))

    assert _lauf(projekt, client, AssertionError("darf nicht fragen")) == 0

    assert projekt["profil_pfad"].read_text(encoding="utf-8") == _PROFIL
    assert _verarbeitet(projekt) == [1]
    assert "KPMG falsch gelesen" in capsys.readouterr().out


def test_nur_unbrauchbare_aenderungen_bleiben_unverarbeitet(
    projekt: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    kaputt = {"alt": "gibt es nicht", "neu": "x", "grund": "g"}

    assert _lauf(projekt, _FakeClient(_vorschlag([kaputt])), AssertionError("nicht fragen")) == 1

    assert projekt["profil_pfad"].read_text(encoding="utf-8") == _PROFIL
    assert _verarbeitet(projekt) == [0]
    assert "gibt es nicht" in capsys.readouterr().err


def test_api_fehler_aendert_nichts(projekt: dict[str, Path]) -> None:
    assert _lauf(projekt, _FakeClient(_api_fehler())) == 1

    assert projekt["profil_pfad"].read_text(encoding="utf-8") == _PROFIL
    assert _verarbeitet(projekt) == [0]


def test_ohne_offenes_feedback_kein_api_aufruf(projekt: dict[str, Path]) -> None:
    client = _FakeClient(_vorschlag())
    _lauf(projekt, client, "n")
    client.aufrufe.clear()

    assert _lauf(projekt, client, "n") == 0

    assert client.aufrufe == []


def test_verarbeitetes_feedback_wird_nicht_erneut_geschickt(projekt: dict[str, Path]) -> None:
    client = _FakeClient(_vorschlag([]))
    _lauf(projekt, client, "n")
    _feedback_anlegen(projekt["db_pfad"], "a-2")
    client.aufrufe.clear()

    _lauf(projekt, client, "n")

    text = client.aufrufe[0]["messages"][0]["content"]
    assert '"anzeige_id": "a-2"' in text
    assert '"anzeige_id": "a-1"' not in text


def test_fehlendes_profil_ist_fehler(projekt: dict[str, Path]) -> None:
    projekt["profil_pfad"].unlink()
    client = _FakeClient(_vorschlag())

    assert _lauf(projekt, client) == 1

    assert client.aufrufe == []
