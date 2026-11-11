"""Tests fuer config.py: `config.toml` mit deutschen Schluesseln lesen."""

from pathlib import Path

from jobagent.config import Config, load_config


def test_load_config_reads_german_keys_from_config_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'wo = "München"\numkreis = 30\nveroeffentlichtseit = 1\nmindest_score = 4\n'
        "nachfassen_ab_tag = 10\nnachfassen_bis_tag = 20\n"
        'was = ["Full-Stack-Entwickler", "Data Scientist"]\n\n'
        '[[firmen]]\nname = "GitLab"\nats = "greenhouse"\nslug = "gitlab"\n',
        encoding="utf-8",
    )

    assert load_config(config_path) == Config(
        keywords=["Full-Stack-Entwickler", "Data Scientist"],
        location="München",
        radius=30,
        published_since=1,
        min_score=4,
        follow_up_min_days=10,
        follow_up_max_days=20,
        companies=[{"name": "GitLab", "ats": "greenhouse", "slug": "gitlab"}],
    )


def test_load_config_uses_defaults_for_missing_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('was = ["A"]\n', encoding="utf-8")

    assert load_config(config_path) == Config(
        keywords=["A"], min_score=3, follow_up_min_days=14, follow_up_max_days=28
    )
