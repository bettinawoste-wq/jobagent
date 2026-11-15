"""Tests fuer config.py: `config.toml` in Abschnitten mit deutschen Schluesseln lesen."""

from pathlib import Path

import pytest

from jobagent.config import Config, ConfigError, load_config
from jobagent.sources.watchlist import WatchlistCompany


def _write(tmp_path: Path, text: str) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(text, encoding="utf-8")
    return config_path


def test_load_config_reads_sections_with_german_keys(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path,
        '[suche]\nwas = ["Full-Stack-Entwickler", "Data Scientist"]\nwo = "München"\n'
        "veroeffentlichtseit = 1\n\n"
        "[bundesagentur]\numkreis = 30\n\n"
        '[[watchlist.firmen]]\nname = "GitLab"\nats = "greenhouse"\nslug = "gitlab"\n\n'
        "[report]\nmindest_score = 4\nnachfassen_ab_tag = 10\nnachfassen_bis_tag = 20\n",
    )

    assert load_config(config_path) == Config(
        keywords=["Full-Stack-Entwickler", "Data Scientist"],
        location="München",
        radius=30,
        published_since=1,
        min_score=4,
        follow_up_min_days=10,
        follow_up_max_days=20,
        companies=[WatchlistCompany(name="GitLab", ats="greenhouse", slug="gitlab")],
    )


def test_load_config_uses_defaults_for_missing_keys_and_sections(tmp_path: Path) -> None:
    config_path = _write(tmp_path, '[suche]\nwas = ["A"]\n')

    assert load_config(config_path) == Config(
        keywords=["A"], min_score=3, follow_up_min_days=14, follow_up_max_days=28
    )


@pytest.mark.parametrize(
    ("old_toml", "old_key", "new_place"),
    [
        ("umkreis = 30", "umkreis", "[bundesagentur] umkreis"),
        ("mindest_score = 4", "mindest_score", "[report] mindest_score"),
        ('was = ["A"]', "was", "[suche] was"),
        ('[[firmen]]\nname = "GitLab"', "firmen", "[[watchlist.firmen]]"),
    ],
)
def test_load_config_rejects_old_flat_key_and_names_its_new_place(
    tmp_path: Path, old_toml: str, old_key: str, new_place: str
) -> None:
    config_path = _write(tmp_path, old_toml + "\n")

    with pytest.raises(ConfigError) as error:
        load_config(config_path)

    assert f"`{old_key}`" in str(error.value)
    assert new_place in str(error.value)


@pytest.mark.parametrize(
    ("toml", "found", "new_place"),
    [
        ('[suche]\nwas = ["A"]\numkreis = 30', "`[suche] umkreis`", "`[bundesagentur] umkreis`"),
        ('[[suche.firmen]]\nname = "GitLab"', "`[[suche.firmen]]`", "`[[watchlist.firmen]]`"),
    ],
)
def test_load_config_rejects_known_key_in_wrong_section_and_names_its_place(
    tmp_path: Path, toml: str, found: str, new_place: str
) -> None:
    config_path = _write(tmp_path, toml + "\n")

    with pytest.raises(ConfigError) as error:
        load_config(config_path)

    assert found in str(error.value)
    assert new_place in str(error.value)
    assert "flache Format" not in str(error.value)


def test_load_config_reports_all_problems_at_once(tmp_path: Path) -> None:
    config_path = _write(tmp_path, 'suche = "wo"\numkreis = 30\n')

    with pytest.raises(ConfigError) as error:
        load_config(config_path)

    assert "`[suche]`" in str(error.value)
    assert "`[bundesagentur] umkreis`" in str(error.value)
    assert "flache Format" in str(error.value)


def test_load_config_rejects_section_that_is_no_table(tmp_path: Path) -> None:
    config_path = _write(tmp_path, 'suche = "wo"\n')

    with pytest.raises(ConfigError) as error:
        load_config(config_path)

    assert "`suche` muss ein Abschnitt `[suche]` sein" in str(error.value)


@pytest.mark.parametrize(
    "toml",
    [
        '[watchlist.firmen]\nname = "GitLab"',
        '[watchlist]\nfirmen = "GitLab"',
        '[firmen]\nname = "GitLab"',
    ],
)
def test_load_config_names_list_of_tables_for_companies_in_wrong_shape(
    tmp_path: Path, toml: str
) -> None:
    config_path = _write(tmp_path, toml + "\n")

    with pytest.raises(ConfigError) as error:
        load_config(config_path)

    assert "`[[watchlist.firmen]]`" in str(error.value)


@pytest.mark.parametrize(
    ("toml", "companies"),
    [
        ("[watchlist]\nfirmen = []", []),
        (
            '[watchlist]\nfirmen = [{ name = "A", ats = "lever", slug = "a" }]',
            [WatchlistCompany(name="A", ats="lever", slug="a")],
        ),
    ],
)
def test_load_config_accepts_empty_and_inline_companies(
    tmp_path: Path, toml: str, companies: list[WatchlistCompany]
) -> None:
    assert load_config(_write(tmp_path, toml + "\n")).companies == companies
