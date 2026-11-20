"""Tests fuer config.py: `config.toml` in Abschnitten mit deutschen Schluesseln lesen."""

from pathlib import Path

import pytest

from jobagent.config import Config, ConfigError, load_config
from jobagent.sources.watchlist import WatchlistCompany


def _write(tmp_path: Path, text: str) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(text, encoding="utf-8")
    return config_path


def test_load_config_names_file_that_is_not_utf8(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_bytes('[suche]\nwo = "München"\n'.encode("cp1252"))

    with pytest.raises(ConfigError, match="config.toml ist nicht in UTF-8 gespeichert"):
        load_config(config_path)


def test_load_config_reads_utf8_with_bom_from_windows_editors(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[suche]\nwo = "München"\n', encoding="utf-8-sig")

    assert load_config(config_path).location == "München"


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


def test_load_config_names_given_file_when_misplaced(tmp_path: Path) -> None:
    config_path = tmp_path / "andere.toml"
    config_path.write_text("umkreis = 30\n", encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        load_config(config_path)

    assert str(error.value).startswith(f"{config_path} ist ungültig:")


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


def _error_of(config_path: Path) -> str:
    with pytest.raises(ConfigError) as error:
        load_config(config_path)
    return str(error.value)


def test_load_config_rejects_unknown_key_and_suggests_closest_name(tmp_path: Path) -> None:
    message = _error_of(_write(tmp_path, "[report]\nmindestscore = 4\n"))

    assert "`[report] mindestscore` unbekannt, meintest du `mindest_score`?" in message


def test_load_config_rejects_unknown_section_and_suggests_closest_name(tmp_path: Path) -> None:
    message = _error_of(_write(tmp_path, '[Suche]\nwas = ["A"]\n'))

    assert "Abschnitt `[Suche]` unbekannt, meintest du `[suche]`?" in message


def test_load_config_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    message = _error_of(_write(tmp_path, "sprache = 1\n"))

    assert "`sprache` unbekannt" in message


def test_load_config_suggests_place_of_known_key_for_unknown_flat_key(tmp_path: Path) -> None:
    message = _error_of(_write(tmp_path, "mindestscore = 4\n"))

    assert "`mindestscore` unbekannt, meintest du `[report] mindest_score`?" in message


@pytest.mark.parametrize(
    ("toml", "expected"),
    [
        ('[suche]\nwas = "Data Scientist"', "`[suche] was` muss eine Liste von Texten sein"),
        ("[suche]\nwas = [1, 2]", "`[suche] was` muss eine Liste von Texten sein"),
        ("[suche]\nwo = 80331", "`[suche] wo` muss ein Text sein"),
        (
            '[suche]\nveroeffentlichtseit = "7"',
            "`[suche] veroeffentlichtseit` muss eine ganze Zahl sein",
        ),
        ("[bundesagentur]\numkreis = 30.5", "`[bundesagentur] umkreis` muss eine ganze Zahl sein"),
        ("[report]\nmindest_score = true", "`[report] mindest_score` muss eine ganze Zahl sein"),
        (
            '[report]\nnachfassen_ab_tag = "14"',
            "`[report] nachfassen_ab_tag` muss eine ganze Zahl sein",
        ),
        (
            "[report]\nnachfassen_bis_tag = []",
            "`[report] nachfassen_bis_tag` muss eine ganze Zahl sein",
        ),
    ],
)
def test_load_config_rejects_wrong_value_type_and_names_expected_type(
    tmp_path: Path, toml: str, expected: str
) -> None:
    assert expected in _error_of(_write(tmp_path, toml + "\n"))


@pytest.mark.parametrize(
    ("toml", "expected"),
    [
        (
            '[[watchlist.firmen]]\nname = "GitLab"\natz = "greenhouse"',
            "`[[watchlist.firmen]] atz` unbekannt, meintest du `ats`?",
        ),
        ("[[watchlist.firmen]]\nslug = 42", "`[[watchlist.firmen]] slug` muss ein Text sein"),
    ],
)
def test_load_config_checks_fields_of_watchlist_companies(
    tmp_path: Path, toml: str, expected: str
) -> None:
    assert expected in _error_of(_write(tmp_path, toml + "\n"))


def test_load_config_collects_unknown_keys_and_wrong_types_in_one_message(
    tmp_path: Path,
) -> None:
    config_path = _write(
        tmp_path, '[suche]\nwas = "Data Scientist"\n\n[report]\nmindestscore = 4\n'
    )

    message = _error_of(config_path)

    assert message.startswith(f"{config_path} ist ungültig:")
    assert "`[suche] was` muss eine Liste von Texten sein" in message
    assert "`[report] mindestscore` unbekannt" in message


def test_load_config_reads_config_toml_of_the_repo() -> None:
    config = load_config(Path(__file__).parent.parent / "config.toml")

    assert config.keywords
    assert config.companies
