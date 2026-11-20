"""Der Lauf: suchen, deduplizieren, bewerten, Report schreiben.

Der Lauf bekommt alles übergeben, was er braucht, und liest selbst weder Dateien noch Uhr
noch Umgebung. Zusammengebaut wird er in `jobagent.main`.
"""

import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from jobagent import report
from jobagent.config import Config
from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModel
from jobagent.position import position_key
from jobagent.report import SourceStatus
from jobagent.score import Assessment, score_job_ad
from jobagent.search_window import SearchWindow
from jobagent.sources import SearchResult, Source
from jobagent.store import Store, description_hash

logger = logging.getLogger(__name__)

_PROFILE_SUGGESTION_MIN_FEEDBACK = 5


def run(
    *,
    sources: Sequence[Source],
    language_model: LanguageModel,
    search_profile: str,
    db: Store,
    config: Config,
    today: date,
    output_dir: Path,
    search_window: SearchWindow,
) -> Path:
    """Führt einen Lauf aus und gibt den Pfad des geschriebenen Reports zurück.

    Die `sources` suchen bereits im Suchzeitraum `search_window`; der Lauf nennt ihn im
    Report. Bewertet wird jede neue Anzeige mit `language_model` gegen das Suchprofil
    `search_profile`. In `db` merkt sich der Lauf die bewerteten Anzeigen, die
    Treffernummern des Reports und, wenn er vollständig war, sich selbst.
    Scheitert der Report (`ReportError`) oder das Merken (`StoreError`), merkt er sich
    nichts und lässt keinen Report liegen: Die Treffer kommen im nächsten Lauf wieder.
    """
    job_ads, source_status = _search_all(sources, config.keywords)
    new_matches, unassessed = _new_matches(db, job_ads, language_model, search_profile)
    complete = unassessed == 0 and not any(status.errors for status in source_status)
    return _report_and_remember(
        db,
        new_matches,
        source_status,
        unassessed,
        config,
        today,
        output_dir,
        search_window,
        complete=complete,
    )


def _report_and_remember(
    db: Store,
    new_matches: list[report.Match],
    source_status: list[SourceStatus],
    unassessed: int,
    config: Config,
    today: date,
    output_dir: Path,
    search_window: SearchWindow,
    *,
    complete: bool,
) -> Path:
    """Schreibt den Report und merkt Treffer samt Treffernummern: alles oder nichts.

    Ein vollständiger Lauf merkt sich mit, damit der nächste Suchzeitraum ab ihm rechnet.
    """
    written: report.WrittenReport | None = None
    # Vor dem Merken: Sonst verglich eine Bewerbung auf genau diese Anzeige deren Text
    # mit sich selbst statt mit dem Text zum Zeitpunkt der Bewerbung.
    applications = _already_applied(db, new_matches)
    try:
        with db.transaction():
            for job_ad, assessment in new_matches:
                db.remember_job_ad(job_ad, assessment, today)
            written = _write_report(
                db,
                new_matches,
                source_status,
                unassessed,
                applications,
                config,
                today,
                output_dir,
                search_window,
            )
            db.save_match_numbers(written.path.stem, written.match_numbers)
            if complete:
                db.remember_complete_run(today, written.path.stem)
    except BaseException:
        # Ohne gemerkte Treffernummern liefen die Nummern dieses Reports ins Leere.
        if written is not None:
            _remove_report(written.path)
        raise
    return written.path


def _remove_report(path: Path) -> None:
    # Lässt er sich nicht löschen, bleibt der erste Fehler der gemeldete.
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning(
            "Report ohne gemerkte Treffernummern ließ sich nicht löschen, bitte von Hand "
            "löschen (report=%s)",
            path,
        )


def _write_report(
    db: Store,
    new_matches: list[report.Match],
    source_status: list[SourceStatus],
    unassessed: int,
    applications: dict[str, report.AlreadyApplied],
    config: Config,
    today: date,
    output_dir: Path,
    search_window: SearchWindow,
) -> report.WrittenReport:
    return report.write_report(
        new_matches,
        today,
        output_dir,
        search_window=search_window,
        sources=source_status,
        unassessed=unassessed,
        min_score=config.min_score,
        applications=applications,
        follow_ups=db.follow_up_reminders(
            today,
            min_days=config.follow_up_min_days,
            max_days=config.follow_up_max_days,
        ),
        open_feedback=_open_feedback(db),
    )


def _new_matches(
    db: Store,
    job_ads: list[JobAd],
    language_model: LanguageModel,
    search_profile: str,
) -> tuple[list[report.Match], int]:
    """Bewertet die neuen Anzeigen; gibt die Treffer und die Zahl der unbewerteten zurück.

    Gemerkt werden die Treffer erst zusammen mit dem Report, siehe `_report_and_remember`.
    """
    matches: list[report.Match] = []
    unassessed = 0

    for job_ad in job_ads:
        if not db.is_new(job_ad.id):
            continue

        assessment = _safe_score(job_ad, search_profile, language_model)
        if assessment is None:
            logger.warning(
                "Anzeige unbewertet, der nächste Lauf versucht es erneut (anzeige=%r)", job_ad.id
            )
            unassessed += 1
            continue

        matches.append((job_ad, assessment))

    return matches, unassessed


def _safe_score(
    job_ad: JobAd, search_profile: str, language_model: LanguageModel
) -> Assessment | None:
    # Bekannte Fehler des Sprachmodells behandelt die Bewertung selbst. Dieses Netz fängt
    # z.B. einen Programmfehler in der Prüfung ab: Eine Bewertung darf den Lauf nie abbrechen.
    try:
        return score_job_ad(job_ad, search_profile, language_model)
    except Exception:
        logger.exception("Unerwarteter Fehler in der Bewertung (anzeige=%r)", job_ad.id)
        return None


def _open_feedback(db: Store) -> int:
    count = db.count_open_feedback()
    return count if count >= _PROFILE_SUGGESTION_MIN_FEEDBACK else 0


def _already_applied(db: Store, matches: list[report.Match]) -> dict[str, report.AlreadyApplied]:
    result: dict[str, report.AlreadyApplied] = {}
    for job_ad, _ in matches:
        # Nur der Titel reicht nicht, um eine Stelle zu erkennen; die Anzeige selbst schon.
        key = position_key(job_ad.company, job_ad.title) if job_ad.company else None
        application = db.current_application(key, job_ad_id=job_ad.id)
        if application is not None:
            result[job_ad.id] = report.AlreadyApplied(
                application.status,
                application.applied_on,
                _text_differs(description_hash(job_ad.description), application.description_hash),
            )
    return result


def _text_differs(new: str | None, at_application: str | None) -> report.TextComparison:
    if new is None or at_application is None:
        return report.TextComparison.NOT_COMPARABLE
    if new == at_application:
        return report.TextComparison.IDENTICAL
    return report.TextComparison.DIFFERS


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


def _safe_search(source: Source, keywords: list[str]) -> SearchResult:
    # Bekannte Netzwerk- und API-Fehler behandelt die Quelle selbst. Dieses Netz fängt
    # z.B. ein geändertes Antwortformat ab: Eine Quelle darf den Lauf nie abbrechen.
    try:
        return source.search(keywords)
    except Exception:
        logger.exception("Unerwarteter Fehler in Quelle %r", source.name)
        # Wie bei Arbeitnow nennt der Fehler alle Suchbegriffe, denen die Suche galt.
        return SearchResult([], [f"{', '.join(keywords)}: unerwarteter Fehler"])
