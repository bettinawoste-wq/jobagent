"""Tests für den Suchzeitraum: Tage seit dem letzten vollständigen Lauf plus 1."""

from datetime import date

from jobagent.search_window import MAX_SEARCH_WINDOW_DAYS, SearchWindow, search_window

THURSDAY = date(2026, 11, 19)
MONDAY = date(2026, 11, 16)


def test_first_run_searches_the_configured_days() -> None:
    assert search_window(None, THURSDAY, max_days=7) == SearchWindow(7, since=None, capped=False)


def test_first_run_without_configured_days_has_no_limit() -> None:
    assert search_window(None, THURSDAY, max_days=None) == SearchWindow(None, None, False)


def test_gap_of_several_days_reaches_back_to_last_complete_run() -> None:
    assert search_window(MONDAY, THURSDAY, max_days=7) == SearchWindow(4, MONDAY, False)


def test_complete_run_yesterday_gives_two_days() -> None:
    assert search_window(date(2026, 11, 18), THURSDAY, max_days=7).days == 2


def test_complete_run_today_gives_one_day() -> None:
    assert search_window(THURSDAY, THURSDAY, max_days=7).days == 1


def test_window_is_capped_at_configured_days() -> None:
    since = date(2026, 11, 1)

    assert search_window(since, THURSDAY, max_days=7) == SearchWindow(7, since, capped=True)


def test_window_without_configured_days_is_not_capped_within_the_upper_limit() -> None:
    since = date(2026, 11, 1)

    assert search_window(since, THURSDAY, max_days=None) == SearchWindow(19, since, False)


def test_upper_limit_matches_what_the_bundesagentur_accepts() -> None:
    # Laut Doku von bundesAPI/jobsuche-api: veroeffentlichtseit zwischen 0 und 100 Tagen.
    assert MAX_SEARCH_WINDOW_DAYS == 100


def test_window_without_configured_days_is_capped_at_the_upper_limit() -> None:
    since = date(2025, 1, 1)

    assert search_window(since, THURSDAY, max_days=None) == SearchWindow(100, since, capped=True)


def test_complete_run_in_the_future_does_not_count() -> None:
    # Etwa nach einer verstellten Uhr: Dann gilt der Startwert wie beim ersten Lauf.
    window = search_window(date(2026, 11, 25), THURSDAY, max_days=7)

    assert window == SearchWindow(7, since=None, capped=False)
