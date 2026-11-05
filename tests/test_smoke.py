"""Dummy-Test, der das Projektgeruest absichert."""

import jobagent


def test_package_importable() -> None:
    assert jobagent is not None
