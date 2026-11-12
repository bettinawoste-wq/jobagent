"""Ablauf: suchen, dedupe, score, report."""

import argparse
import io
import logging
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from jobagent import demo, report, score, store
from jobagent.config import Config, load_config
from jobagent.job_ad import JobAd
from jobagent.position import position_key
from jobagent.sources import SearchResult, Source
from jobagent.sources.arbeitnow import ArbeitnowSource
from jobagent.sources.bundesagentur import BundesagenturSource
from jobagent.sources.watchlist import WatchlistSource

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config.toml")
_PROFILE_PATH = Path("profile.md")
_DB_PATH = Path("jobagent.db")
_PROFILE_SUGGESTION_MIN_FEEDBACK = 5

Assess = Callable[[JobAd], score.Assessment | None]
"""Bewertet eine Anzeige; None heisst: diesmal nicht bewertbar, naechster Lauf versucht es neu."""


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """Was eine Quelle in diesem Lauf geliefert hat; steht im Quellenstatus des Reports."""

    name: str
    count: int
    errors: list[str] = field(default_factory=list)


def main(
    *,
    config_path: Path = _CONFIG_PATH,
    profile_path: Path = _PROFILE_PATH,
    db_path: Path = _DB_PATH,
    output_dir: Path = report.OUTPUT_DIR,
    config: Config | None = None,
    sources: Sequence[Source] | None = None,
    assess: Assess | None = None,
) -> Path:
    """Fuehrt einen Lauf aus: suchen, deduplizieren, bewerten, Report schreiben.

    Ohne `config`, `sources` und `assess` gilt `config.toml`, die eingebauten Quellen
    und die Haiku-Bewertung gegen `profile.md`. Wer sie angibt, ersetzt sie: Dann wird
    die jeweilige Datei nicht gelesen und das jeweilige Netz bzw. Modell nicht gefragt.
    """
    logging.basicConfig(level=logging.INFO)

    if config is None:
        config = load_config(config_path)
    if sources is None:
        sources = default_sources(config)
    if assess is None:
        assess = _haiku_assessment(profile_path.read_text(encoding="utf-8"))
    today = date.today()

    conn = store.connect(db_path)
    try:
        job_ads, source_status = _search_all(sources, config.keywords)
        new_matches = _new_matches(conn, job_ads, assess, today)
        written = report.write_report(
            new_matches,
            today,
            output_dir,
            sources=source_status,
            min_score=config.min_score,
            applications=_already_applied(conn, new_matches),
            follow_ups=store.follow_up_reminders(
                conn,
                today,
                min_days=config.follow_up_min_days,
                max_days=config.follow_up_max_days,
            ),
            open_feedback=_open_feedback(conn),
        )
        store.save_match_numbers(conn, written.path.stem, written.match_numbers)
        return written.path
    finally:
        conn.close()


def _haiku_assessment(profile: str) -> Assess:
    return lambda job_ad: score.score_job_ad(job_ad, profile)


def _new_matches(
    conn: sqlite3.Connection,
    job_ads: list[JobAd],
    assess: Assess,
    today: date,
) -> list[report.Match]:
    matches: list[report.Match] = []

    for job_ad in job_ads:
        if not store.is_new(conn, job_ad.id):
            continue

        assessment = assess(job_ad)
        if assessment is None:
            logger.warning("Bewertung uebersprungen, bleibt fuer naechsten Lauf (id=%r)", job_ad.id)
            continue

        store.mark_seen(conn, job_ad, assessment, today)
        matches.append((job_ad, assessment))

    return matches


def _open_feedback(conn: sqlite3.Connection) -> int:
    count = store.count_open_feedback(conn)
    return count if count >= _PROFILE_SUGGESTION_MIN_FEEDBACK else 0


def _already_applied(
    conn: sqlite3.Connection, matches: list[report.Match]
) -> dict[str, report.AlreadyApplied]:
    result: dict[str, report.AlreadyApplied] = {}
    for job_ad, _ in matches:
        if not job_ad.company:  # Nur der Titel reicht nicht, um eine Stelle zu erkennen.
            continue
        application = store.latest_application(conn, position_key(job_ad.company, job_ad.title))
        if application is not None:
            result[job_ad.id] = report.AlreadyApplied(
                application.status,
                application.applied_on,
                _text_differs(
                    store.description_hash(job_ad.description), application.description_hash
                ),
            )
    return result


def _text_differs(new: str | None, at_application: str | None) -> str:
    if new is None or at_application is None:
        return "Text nicht vergleichbar"
    return "Text identisch" if new == at_application else "Text weicht von deiner Bewerbung ab"


def _search_all(
    sources: Sequence[Source], keywords: list[str]
) -> tuple[list[JobAd], list[SourceStatus]]:
    found: dict[str, JobAd] = {}
    status: list[SourceStatus] = []

    for source in sources:
        result = _safe_search(source, keywords)
        ids = {job_ad.id for job_ad in result.job_ads}
        for job_ad in result.job_ads:
            found.setdefault(job_ad.id, job_ad)
        errors = list(dict.fromkeys(result.errors))  # doppelte weg, Reihenfolge bleibt
        status.append(SourceStatus(source.name, len(ids), errors))

    return list(found.values()), status


def default_sources(
    config: Config, *, transport: httpx.BaseTransport | None = None
) -> list[Source]:
    """Die eingebauten Quellen; die Firmen-Watchlist nur, wenn `config.toml` Firmen nennt."""
    location = config.location
    since = config.published_since

    sources: list[Source] = [
        BundesagenturSource(location, config.radius, since, transport=transport),
        ArbeitnowSource(location, since, transport=transport),
    ]
    if config.companies:
        sources.append(WatchlistSource(config.companies, transport=transport))
    return sources


def _safe_search(source: Source, keywords: list[str]) -> SearchResult:
    # Bekannte Netzwerk- und API-Fehler behandelt die Quelle selbst. Dieses Netz faengt
    # z.B. ein geaendertes Antwortformat ab: Eine Quelle darf den Lauf nie abbrechen.
    try:
        return source.search(keywords)
    except Exception:
        logger.exception("Unerwarteter Fehler in Quelle %r", source.name)
        # Wie bei Arbeitnow nennt der Fehler alle Suchbegriffe, denen die Suche galt.
        return SearchResult([], [f"{', '.join(keywords)}: unerwarteter Fehler"])


def cli(argv: list[str] | None = None) -> None:
    """Kommandozeile: ein echter Lauf oder mit `--demo` ein Demo-Lauf."""
    parser = argparse.ArgumentParser(prog="python -m jobagent.main")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Demo-Lauf: erfundene Anzeigen und vorgefertigte Bewertungen, ohne API-Key und "
        "ohne Netz; der Report erscheint auf stdout",
    )
    parser.add_argument(
        "--ausgabe",
        dest="output",
        type=Path,
        metavar="ORDNER",
        help="nur mit --demo: Report zusätzlich als Datei in ORDNER schreiben",
    )
    args = parser.parse_args(argv)
    if args.output is not None and not args.demo:
        parser.error("--ausgabe gibt es nur zusammen mit --demo")

    if args.demo:
        _write_utf8(demo_run(args.output))
    else:
        main()


def demo_run(output_dir: Path | None = None) -> str:
    """Fuehrt einen Demo-Lauf aus und liefert den Report-Text.

    Datenbank und Report liegen in einem temporaeren Ordner, der danach verschwindet;
    nur mit `output_dir` bleibt der Report zusaetzlich dort als Datei liegen.
    """
    with tempfile.TemporaryDirectory(prefix="jobagent-demo-") as temp:
        db_path = Path(temp) / "demo.db"
        conn = store.connect(db_path)
        try:
            demo.create_applications(conn, date.today())
        finally:
            conn.close()
        path = main(
            db_path=db_path,
            output_dir=output_dir or Path(temp),
            config=demo.CONFIG,
            sources=demo.sources(),
            assess=demo.assess,
        )
        return path.read_text(encoding="utf-8")


def _write_utf8(text: str) -> None:
    # Die Windows-Konsole nutzt sonst eine Codepage, in der Umlaute kaputtgehen.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    cli()
