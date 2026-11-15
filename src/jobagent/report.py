"""Schreibt output/YYYY-MM-DD.md, sortiert nach Score."""

from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from jobagent.job_ad import JobAd
from jobagent.score import Assessment
from jobagent.store import FollowUpReminder

if TYPE_CHECKING:  # run importiert report; nur der Typ wird gebraucht
    from jobagent.run import SourceStatus

OUTPUT_DIR = Path("output")
DEFAULT_MIN_SCORE = 3

Match = tuple[JobAd, Assessment]


class ReportError(Exception):
    """Der Report laesst sich nicht schreiben; die Meldung nennt den Report-Ordner."""


@dataclass(frozen=True, slots=True)
class WrittenReport:
    path: Path
    match_numbers: dict[str, int]  # Anzeigen-ID -> Treffernummer


@dataclass(frozen=True, slots=True)
class AlreadyApplied:
    status: str
    applied_on: date
    text_comparison: str


def write_report(
    matches: list[Match],
    day: date,
    output_dir: Path = OUTPUT_DIR,
    sources: Sequence["SourceStatus"] = (),
    min_score: int = DEFAULT_MIN_SCORE,
    applications: Mapping[str, AlreadyApplied] | None = None,
    follow_ups: Sequence[FollowUpReminder] = (),
    open_feedback: int = 0,
    unassessed: int = 0,
) -> WrittenReport:
    """Schreibt die Treffer sortiert nach Score und nummeriert in output/YYYY-MM-DD.md.

    Ohne Treffer wird eine kurze Notiz statt einer leeren Datei erzeugt.
    Ein vorhandener Report wird nie ueberschrieben, siehe _open_new_report. Laesst sich der
    Report nicht schreiben, wirft `ReportError`.
    """
    header = (
        f"# Stellenvorschläge {day.isoformat()}\n\n"
        f"{_sources_block(sources)}{_unassessed_line(unassessed)}"
        f"{_follow_up_block(follow_ups, day)}"
        f"{_profile_hint(open_feedback)}"
    )

    if not matches:
        path = _save(f"{header}Keine neuen Treffer heute.\n", output_dir, day)
        return WrittenReport(path, {})

    ranked = sorted(matches, key=lambda match: match[1].score, reverse=True)
    applications = applications or {}
    open_matches = [match for match in ranked if match[0].id not in applications]
    applied = [match for match in ranked if match[0].id in applications]
    numbered = list(enumerate(open_matches + applied, start=1))

    numbered_open = numbered[: len(open_matches)]
    full = [entry for entry in numbered_open if entry[1][1].score >= min_score]
    compact = [entry for entry in numbered_open if entry[1][1].score < min_score]

    parts = [_section(number, job_ad, assessment) for number, (job_ad, assessment) in full]
    if compact:
        parts.append(_compact_block(compact, min_score))
    if applied:
        parts.append(_applied_block(numbered[len(open_matches) :], applications))

    path = _save(header + "\n".join(parts), output_dir, day)
    return WrittenReport(path, {job_ad.id: number for number, (job_ad, _) in numbered})


def _save(content: str, output_dir: Path, day: date) -> Path:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        file, path = _open_new_report(output_dir, day)
    except OSError as error:
        raise _report_error(output_dir, error) from error
    # Kein halb geschriebener Report bleibt liegen.
    try:
        with file:
            file.write(content)
    except OSError as error:
        _discard(path)
        raise _report_error(output_dir, error) from error
    except BaseException:
        _discard(path)
        raise
    return path


def _discard(path: Path) -> None:
    with suppress(OSError):
        path.unlink()


def _open_new_report(output_dir: Path, day: date) -> tuple[TextIO, Path]:
    # Gesehene Anzeigen kommen nie wieder, ein ueberschriebener Report waere
    # also endgueltig verloren. Weitere Laeufe am selben Tag bekommen -2, -3, ...
    # "x" legt die Datei nur neu an, auch wenn ein gleichzeitiger Lauf denselben Namen will.
    run_number = 1
    while True:
        suffix = "" if run_number == 1 else f"-{run_number}"
        path = output_dir / f"{day.isoformat()}{suffix}.md"
        run_number += 1
        if path.exists():  # unter Windows meldet "x" einen Ordner nicht als vorhanden
            continue
        try:
            return path.open("x", encoding="utf-8"), path
        except FileExistsError:
            continue


def _report_error(output_dir: Path, error: OSError) -> ReportError:
    return ReportError(
        f"Report lässt sich nicht in {output_dir} schreiben: {error.strerror or error}"
    )


def _sources_block(sources: Sequence["SourceStatus"]) -> str:
    if not sources:
        return ""
    lines = "\n".join(_source_line(source) for source in sources)
    return f"## Quellen\n{lines}\n\n"


def _source_line(source: "SourceStatus") -> str:
    count = "1 Anzeige" if source.count == 1 else f"{source.count} Anzeigen"
    if not source.errors:
        return f"- {source.name}: {count}"
    return f"- {source.name}: FEHLER, {count} ({'; '.join(source.errors)})"


def _unassessed_line(unassessed: int) -> str:
    if not unassessed:
        return ""
    count = "1 unbewertete Anzeige" if unassessed == 1 else f"{unassessed} unbewertete Anzeigen"
    return f"{count} – der nächste Lauf versucht es erneut.\n\n"


def _profile_hint(open_feedback: int) -> str:
    if not open_feedback:
        return ""
    return (
        f"## Profil-Vorschlag\n- {open_feedback} Rückmeldungen warten auf Auswertung: "
        "`python -m jobagent.profile_suggestion`\n\n"
    )


def _follow_up_block(follow_ups: Sequence[FollowUpReminder], today: date) -> str:
    if not follow_ups:
        return ""
    lines = "\n".join(_follow_up_line(reminder, today) for reminder in follow_ups)
    return f"## Nachfassen\n{lines}\n\n"


def _follow_up_line(reminder: FollowUpReminder, today: date) -> str:
    days = (today - reminder.applied_on).days
    duration = "1 Tag" if days == 1 else f"{days} Tagen"
    return (
        f"- {reminder.title} ({reminder.company or 'unbekannt'}): seit {duration} keine Antwort, "
        f"nachhaken? (beworben am {reminder.applied_on:%d.%m.%Y})"
    )


def _compact_block(compact: list[tuple[int, Match]], min_score: int) -> str:
    lines = "\n".join(
        _compact_line(number, job_ad, assessment) for number, (job_ad, assessment) in compact
    )
    return f"## Weitere Treffer (Score unter {min_score})\n{lines}\n"


def _compact_line(number: int, job_ad: JobAd, assessment: Assessment) -> str:
    return (
        f"{_line_start(number, job_ad)} – "
        f"Score {assessment.score}/5: {assessment.summary} – {job_ad.link}"
    )


def _applied_block(
    numbered: list[tuple[int, Match]], applications: Mapping[str, AlreadyApplied]
) -> str:
    lines = "\n".join(
        _applied_line(number, job_ad, assessment, applications[job_ad.id])
        for number, (job_ad, assessment) in numbered
    )
    return f"## Bereits beworben\n{lines}\n"


def _applied_line(
    number: int, job_ad: JobAd, assessment: Assessment, application: AlreadyApplied
) -> str:
    return (
        f"{_line_start(number, job_ad)} – Score {assessment.score}/5 – "
        f"{application.status}, beworben am {application.applied_on:%d.%m.%Y} – "
        f"{application.text_comparison} – {job_ad.link}"
    )


def _line_start(number: int, job_ad: JobAd) -> str:
    company = job_ad.company or "unbekannt"
    location = job_ad.location or "unbekannt"
    return f"- **{number}.** {job_ad.title} ({company}, {location})"


def _section(number: int, job_ad: JobAd, assessment: Assessment) -> str:
    lines = [
        f"## {number}. {job_ad.title} – Score {assessment.score}/5",
        f"- Firma: {job_ad.company or 'unbekannt'}",
        f"- Ort: {job_ad.location or 'unbekannt'}",
        f"- Link: {job_ad.link}",
        f"- Kurzfazit: {assessment.summary}",
    ]
    if assessment.fits:
        lines.append(f"- Passt: {', '.join(assessment.fits)}")
    if assessment.misfits:
        lines.append(f"- Passt nicht: {', '.join(assessment.misfits)}")
    if assessment.gaps:
        lines.append(f"- Lücken: {', '.join(assessment.gaps)}")
    lines.append("")
    return "\n".join(lines)
