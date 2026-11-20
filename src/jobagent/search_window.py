"""Der Suchzeitraum eines Laufs: Tage seit dem letzten vollständigen Lauf plus 1."""

from dataclasses import dataclass
from datetime import date

# Obergrenze des Suchzeitraums: Mehr Tage nimmt die Jobsuche-API der Bundesagentur für
# `veroeffentlichtseit` nicht an (Doku von bundesAPI/jobsuche-api: 0 bis 100 Tage).
MAX_SEARCH_WINDOW_DAYS = 100


@dataclass(frozen=True, slots=True)
class SearchWindow:
    """Aus wie vielen zurückliegenden Tagen ein Lauf Anzeigen holt.

    `since` ist der Tag des letzten
    vollständigen Laufs, None beim ersten Lauf; liegt er in der Zukunft, gilt der Startwert.
    `capped` sagt, ob `veroeffentlichtseit` oder die Obergrenze den Suchzeitraum begrenzt hat.
    """

    days: int
    since: date | None
    capped: bool


def search_window(
    last_complete_run: date | None, today: date, *, max_days: int | None
) -> SearchWindow:
    """Berechnet den Suchzeitraum; `max_days` ist `veroeffentlichtseit` aus `[suche]`.

    Fehlt `max_days`, gilt `MAX_SEARCH_WINDOW_DAYS`: Ohne Grenze stießen die Quellen an
    ihre Seitengrenze, und kein Lauf würde je vollständig. Ohne vollständigen Lauf gilt
    dieser Wert als Startwert, ebenso, wenn der gemerkte vollständige Lauf in der Zukunft
    liegt (etwa nach einer verstellten Uhr). Sonst reicht der Suchzeitraum bis zum Tag des
    letzten vollständigen Laufs zurück, mindestens 1 Tag und höchstens dieser Wert.
    """
    limit = MAX_SEARCH_WINDOW_DAYS if max_days is None else max_days
    if last_complete_run is None or last_complete_run > today:
        return SearchWindow(limit, since=last_complete_run, capped=False)
    days = (today - last_complete_run).days + 1
    if days > limit:
        return SearchWindow(limit, last_complete_run, capped=True)
    return SearchWindow(days, last_complete_run, capped=False)
