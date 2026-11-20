"""Der Suchzeitraum eines Laufs: Tage seit dem letzten vollständigen Lauf plus 1."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class SearchWindow:
    """Aus wie vielen zurückliegenden Tagen ein Lauf Anzeigen holt.

    `days` ist None, wenn `veroeffentlichtseit` fehlt und es noch keinen vollständigen
    Lauf gibt: Dann suchen die Quellen ohne Begrenzung. `since` ist der Tag des letzten
    vollständigen Laufs, None beim ersten Lauf; `capped` sagt, ob `veroeffentlichtseit`
    den Suchzeitraum begrenzt hat.
    """

    days: int | None
    since: date | None
    capped: bool


def search_window(
    last_complete_run: date | None, today: date, *, max_days: int | None
) -> SearchWindow:
    """Berechnet den Suchzeitraum; `max_days` ist `veroeffentlichtseit` aus `[suche]`.

    Ohne vollständigen Lauf gilt `max_days` als Startwert. Sonst reicht der Suchzeitraum
    bis zum Tag des letzten vollständigen Laufs zurück, mindestens 1 und höchstens
    `max_days` Tage.
    """
    if last_complete_run is None:
        return SearchWindow(max_days, since=None, capped=False)
    days = max((today - last_complete_run).days + 1, 1)
    if max_days is not None and days > max_days:
        return SearchWindow(max_days, last_complete_run, capped=True)
    return SearchWindow(days, last_complete_run, capped=False)
