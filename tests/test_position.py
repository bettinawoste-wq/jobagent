"""Tests fuer position.py: Wann gelten zwei Anzeigen als dieselbe Stelle?"""

import pytest

from jobagent.position import position_key


@pytest.mark.parametrize(
    ("company_a", "title_a", "company_b", "title_b"),
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
def test_same_position(company_a: str, title_a: str, company_b: str, title_b: str) -> None:
    assert position_key(company_a, title_a) == position_key(company_b, title_b)


@pytest.mark.parametrize(
    ("company_a", "title_a", "company_b", "title_b"),
    [
        ("Firma X", "Data Engineer", "Firma Y", "Data Engineer"),
        ("Firma X", "Data Engineer", "Firma X", "Senior Data Engineer"),
        ("Firma X", "Data/Integration Engineer", "Firma X", "Data Engineer"),
        ("AG", "Dev", "SE", "Dev"),
        ("Firma X", "Team Rot: Consultant", "Firma X", "Consultant"),
    ],
)
def test_different_positions(company_a: str, title_a: str, company_b: str, title_b: str) -> None:
    assert position_key(company_a, title_a) != position_key(company_b, title_b)


def test_company_consisting_only_of_legal_form_is_kept() -> None:
    assert position_key("AG", "Dev") == "ag|dev"


def test_title_consisting_only_of_company_is_kept() -> None:
    assert position_key("Firma X", "Firma X:") == "firma x|firma x"


def test_missing_company_is_allowed() -> None:
    assert position_key(None, "Dev") == "|dev"
