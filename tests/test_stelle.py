"""Tests fuer stelle.py: Wann gelten zwei Anzeigen als dieselbe Stelle?"""

import pytest

from jobagent.stelle import stellen_schluessel


@pytest.mark.parametrize(
    ("firma_a", "titel_a", "firma_b", "titel_b"),
    [
        ("Firma X", "Data Engineer (m/w/d)", "Firma X", "Data Engineer (w/m/x)"),
        ("Firma X", "Data Engineer (m/w/d)", "Firma X", "Data Engineer"),
        ("Firma X", "Data Engineer (m/f/d)", "Firma X", "Data Engineer (all genders)"),
        ("Firma X", "Data Engineer m/w/d", "Firma X", "Data Engineer"),
        ("Firma X", "Entwickler/in (m/w/d)", "Firma X", "Entwickler"),
        ("Firma X", "DATA engineer", "firma x", "Data Engineer"),
        ("Firma X", "Full-Stack Entwickler", "Firma X", "Full Stack Entwickler"),
        ("Beispiel GmbH", "Dev", "Beispiel", "Dev"),
        ("Beispiel GmbH & Co. KG", "Dev", "Beispiel", "Dev"),
        ("NTT DATA Deutschland SE", "Dev", "NTT DATA Deutschland", "Dev"),
        ("Verein e.V.", "Dev", "Verein", "Dev"),
        ("mgm GmbH", "mgm GmbH: Full-Stack (m/w/d)", "mgm GmbH", "Full-Stack"),
        ("NTT DATA SE", "NTT DATA: Consultant", "NTT DATA SE", "Consultant"),
    ],
)
def test_gleiche_stelle(firma_a: str, titel_a: str, firma_b: str, titel_b: str) -> None:
    assert stellen_schluessel(firma_a, titel_a) == stellen_schluessel(firma_b, titel_b)


@pytest.mark.parametrize(
    ("firma_a", "titel_a", "firma_b", "titel_b"),
    [
        ("Firma X", "Data Engineer", "Firma Y", "Data Engineer"),
        ("Firma X", "Data Engineer", "Firma X", "Senior Data Engineer"),
        ("Firma X", "Data/Integration Engineer", "Firma X", "Data Engineer"),
        ("AG", "Dev", "SE", "Dev"),
        ("Firma X", "Team Rot: Consultant", "Firma X", "Consultant"),
    ],
)
def test_verschiedene_stellen(firma_a: str, titel_a: str, firma_b: str, titel_b: str) -> None:
    assert stellen_schluessel(firma_a, titel_a) != stellen_schluessel(firma_b, titel_b)


def test_firma_die_nur_aus_rechtsform_besteht_bleibt_erhalten() -> None:
    assert stellen_schluessel("AG", "Dev") == "ag|dev"


def test_titel_der_nur_aus_firma_besteht_bleibt_erhalten() -> None:
    assert stellen_schluessel("Firma X", "Firma X:") == "firma x|firma x"


def test_fehlende_firma_ist_erlaubt() -> None:
    assert stellen_schluessel(None, "Dev") == "|dev"
