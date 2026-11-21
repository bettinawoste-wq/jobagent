"""Quelle Bundesagentur für Arbeit: Jobsuche-API (siehe CLAUDE.md, Quelle 1)."""

import base64
from dataclasses import dataclass, replace

import httpx

from jobagent.job_ad import JobAd
from jobagent.sources import SearchResult
from jobagent.sources._http import (
    TIMEOUT,
    ConvertedEntries,
    FetchError,
    InvalidEntry,
    convert_entries,
    entries_with_ids,
    get_json,
    malformed_as_invalid,
    required_text,
    text_at,
    text_or_none,
)

_SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
_DETAILS_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}"
_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
# Ergebnisse je Seite, wie im Beispiel der Doku von bundesAPI/jobsuche-api.
_PAGE_SIZE = 50
# Sicherheitsgrenze je Suchbegriff, zur maßvollen Nutzung der API (ADR 0002): Jede
# gefundene Anzeige kostet noch einen Detail-Call.
_MAX_PAGES = 5
# Abgeschnitten ist ein Fehler: Der Lauf zählt dann nicht als vollständig, und der nächste
# Suchzeitraum reicht weiter zurück, statt die übrigen Anzeigen still zu verlieren. Bei
# einem Suchbegriff mit so vielen Treffern hilft nur, ihn enger zu fassen.
_TRUNCATED = f"Ergebnisse abgeschnitten nach {_MAX_PAGES} Seiten, Suchbegriff enger fassen"


class BundesagenturSource:
    """Sucht je Suchbegriff in der Jobsuche-API und holt die Jobdetails je Anzeige einmal.

    Gesucht wird im Suchzeitraum `search_window` (in Tagen, an die API als
    `veroeffentlichtseit`). Je Suchbegriff blättert sie (`page` ab 1, `size`), bis alle
    Ergebnisse da sind, höchstens `_MAX_PAGES` Seiten. Bleiben danach Ergebnisse übrig,
    meldet sie "Ergebnisse abgeschnitten" als Fehler: Der Lauf zählt dann nicht als
    vollständig.

    Scheitert der Detail-Call einer Anzeige, bleibt nur deren Beschreibung leer; das gilt
    nicht als Fehler der Quelle.
    """

    name = "Bundesagentur für Arbeit"

    def __init__(
        self,
        location: str | None = None,
        radius: int | None = None,
        search_window: int | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._location = location
        self._radius = radius
        self._search_window = search_window
        self._transport = transport

    def search(self, keywords: list[str]) -> SearchResult:
        found: dict[str, JobAd] = {}
        errors: list[str] = []
        with httpx.Client(timeout=TIMEOUT, transport=self._transport) as client:
            for keyword in keywords:
                result = self._search_keyword(client, keyword)
                for job_ad in result.job_ads:
                    found.setdefault(job_ad.id, job_ad)
                errors.extend(result.errors)
            # Die Details erst nach dem Zusammenführen holen: je Anzeige nur einmal.
            job_ads = [
                replace(job_ad, description=_description(client, job_ad.id))
                for job_ad in found.values()
            ]
        return SearchResult(job_ads, errors)

    def _search_keyword(self, client: httpx.Client, keyword: str) -> SearchResult:
        """Blättert durch alle Seiten zu einem Suchbegriff, höchstens `_MAX_PAGES`.

        Scheitert eine Seite oder ist die Grenze erreicht, bleiben die Anzeigen der Seiten
        davor erhalten, und der Fehler steht im Ergebnis.
        """
        job_ads: list[JobAd] = []
        errors: list[str] = []
        seen: set[str] = set()
        for page in range(1, _MAX_PAGES + 1):
            try:
                result = self._search_page(client, keyword, page)
            except FetchError as error:
                errors.append(f"{keyword}: {error.reason}")
                break
            job_ads.extend(result.converted.job_ads)
            errors.extend(result.converted.errors(keyword))
            new = set(result.ids) - seen
            seen |= new
            if _last_page(result, len(seen), brought_new=bool(new)):
                break
        else:
            errors.append(f"{keyword}: {_TRUNCATED}")
        # "ungültige Antwort" höchstens einmal je Suchbegriff, auch über mehrere Seiten.
        return SearchResult(job_ads, list(dict.fromkeys(errors)))

    def _search_page(self, client: httpx.Client, keyword: str, page: int) -> "_Page":
        """Eine Ergebnisseite zu einem Suchbegriff, noch ohne Beschreibung."""
        params: dict[str, str | int] = {"was": keyword, "page": page, "size": _PAGE_SIZE}
        if self._location is not None:
            params["wo"] = self._location
        if self._radius is not None:
            params["umkreis"] = self._radius
        if self._search_window is not None:
            params["veroeffentlichtseit"] = self._search_window

        data = get_json(client, _SEARCH_URL, params=params, headers=_HEADERS)
        # Hinweis: Die Live-API liefert ein anderes Schema als die Doku von
        # bundesAPI/jobsuche-api (dort z.B. "stellenangebote"/"refnr"/"arbeitsort"/
        # "externeUrl"). Feldnamen hier sind gegen echte API-Antworten verifiziert.
        entries = entries_with_ids(
            data.get("ergebnisliste", []) if isinstance(data, dict) else None,
            "referenznummer",
            id_type=str,
            what="Jobsuche-Antwort",
            where=f"was={keyword!r}",
        )
        with malformed_as_invalid("Jobsuche-Antwort", f"was={keyword!r}"):
            converted = convert_entries(
                entries, _to_job_ad, what="Jobsuche-Antwort", where=f"was={keyword!r}"
            )
        total = data.get("maxErgebnisse") if isinstance(data, dict) else None
        ids = tuple(entry["referenznummer"] for entry in entries)
        return _Page(converted, ids, _count_or_none(total))


@dataclass(frozen=True, slots=True)
class _Page:
    """Eine Ergebnisseite: ihre Anzeigen, die Referenznummern aller ihrer Einträge und,
    falls die API sie nennt, die Gesamtzahl der Ergebnisse (`maxErgebnisse`)."""

    converted: ConvertedEntries
    ids: tuple[str, ...]
    total: int | None


def _last_page(page: _Page, seen: int, *, brought_new: bool) -> bool:
    """Ob nach dieser Seite nichts mehr kommt; `seen` zählt die verschiedenen Einträge bis hier.

    Nennt die API die Gesamtzahl, endet das Blättern, sobald so viele verschiedene Einträge
    da sind; eine kürzere Seite allein beendet es dann nicht, denn die API muss sich nicht
    an `size` halten. Ohne Gesamtzahl ist eine nicht volle Seite die letzte. Eine Seite
    ohne neue Einträge (leer oder nur Wiederholungen) beendet das Blättern immer.
    """
    if not brought_new:
        return True
    if page.total is not None:
        return seen >= page.total
    return len(page.ids) < _PAGE_SIZE


def _count_or_none(value: object) -> int | None:
    """`maxErgebnisse` als Zahl; die Doku nennt einen Text, die Beispielantwort hat eine Zahl.

    Hat es eine andere Form, ist die Gesamtzahl unbekannt, dann endet das Blättern erst an
    einer nicht vollen Seite.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _to_job_ad(entry: dict) -> JobAd:
    reference = entry["referenznummer"]
    # Ein Link mit falschem Typ zählt wie ein fehlender, dann greift der Ersatz.
    link = (
        text_or_none(entry.get("externeURL"))
        or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}"
    )
    return JobAd(
        id=reference,
        title=_title(entry),
        company=text_or_none(entry.get("firma")),
        location=text_at(entry, "stellenlokationen", 0, "adresse", "ort"),
        link=link,
    )


def _title(entry: dict) -> str:
    """Titel aus `stellenangebotsTitel`, sonst aus dem Ersatz `hauptberuf`.

    Ein Titel mit falschem Typ zählt wie ein fehlender. Bleibt danach kein Titel übrig,
    ist der Eintrag ungültig, statt still ohne Titel im Report zu landen.
    """
    raw = entry.get("stellenangebotsTitel")
    title = text_or_none(raw) or required_text(entry.get("hauptberuf"))
    if not title and raw is not None and not isinstance(raw, str):
        raise InvalidEntry
    return title


def _description(client: httpx.Client, reference: str) -> str | None:
    code = base64.b64encode(reference.encode()).decode()
    try:
        details = get_json(client, _DETAILS_URL.format(code=code), headers=_HEADERS)
    except FetchError:
        return None
    if not isinstance(details, dict):
        return None
    return text_or_none(details.get("stellenangebotsBeschreibung")) or text_or_none(
        details.get("stellenbeschreibung")
    )
