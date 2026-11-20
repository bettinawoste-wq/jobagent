"""Der Suchzeitraum eines Laufs: Tage seit dem letzten vollständigen Lauf plus 1."""

from dataclasses import dataclass
from datetime import date

# Obergrenze des Suchzeitraums: Mehr Tage nimmt die Jobsuche-API der Bundesagentur für
# `veroeffentlichtseit` nicht an (Doku von bundesAPI/jobsuche-api: 0 bis 100 Tage).
MAX_SEARCH_WINDOW_DAYS = 100


@dataclass(frozen=True, slots=True)
class SearchWindow:
    """Aus wie vielen zurückliegenden Tagen ein Lauf Anzeigen holt.

    `days` ist None, wenn `veroeffentlichtseit` fehlt und es noch keinen vollständigen
    Lauf gibt: Dann suchen die Quellen ohne Begrenzung. `since` ist der Tag des letzten
    vollständigen Laufs, None beim ersten Lauf; `capped` sagt, ob `veroeffentlichtseit`
    oder die Obergrenze den Suchzeitraum begrenzt hat.
    """

    days: int | None
    since: date | None
    capped: bool


def search_window(
    last_complete_run: date | None, today: date, *, max_days: int | None
) -> SearchWindow:
    """Berechnet den Suchzeitraum; `max_days` ist `veroeffentlichtseit` aus `[suche]`.

    Ohne vollständigen Lauf gilt `max_days` als Startwert, ebenso, wenn der gemerkte
    vollständige Lauf in der Zukunft liegt (etwa nach einer verstellten Uhr). Sonst reicht
    der Suchzeitraum bis zum Tag des letzten vollständigen Laufs zurück, mindestens 1 und
    höchstens `max_days` Tage; fehlt `max_days`, höchstens `MAX_SEARCH_WINDOW_DAYS`.
    """
    if last_complete_run is None or last_complete_run > today:
        return SearchWindow(max_days, since=None, capped=False)
    days = (today - last_complete_run).days + 1
    limit = MAX_SEARCH_WINDOW_DAYS if max_days is None else max_days
    if days > limit:
        return SearchWindow(limit, last_complete_run, capped=True)
    return SearchWindow(days, last_complete_run, capped=False)
