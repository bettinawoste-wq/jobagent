"""Kommandozeile und Zusammenbau des Laufs.

Hier, und nur hier, werden Konfiguration und Suchprofil gelesen, Quellen, Sprachmodell und
Store gebaut und das Datum bestimmt. Der Lauf selbst steht in `jobagent.run`.
"""

import argparse
import io
import logging
import sys
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import httpx

from jobagent import demo, report
from jobagent.config import Config, ConfigError, load_config
from jobagent.language_model import AnthropicLanguageModel, LanguageModel
from jobagent.logs import RunLog, setup_logging
from jobagent.report import ReportError
from jobagent.run import run
from jobagent.search_profile import SearchProfileError, read_search_profile
from jobagent.sources import Source
from jobagent.sources.arbeitnow import ArbeitnowSource
from jobagent.sources.bundesagentur import BundesagenturSource
from jobagent.sources.watchlist import WatchlistSource
from jobagent.store import Store, StoreError

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config.toml")
_PROFILE_PATH = Path("profile.md")
_DB_PATH = Path("jobagent.db")
_ASSESSMENT_MODEL = "claude-haiku-4-5-20251001"  # Haiku für die Bewertung (ADR 0004)


def main(
    *,
    config_path: Path = _CONFIG_PATH,
    profile_path: Path = _PROFILE_PATH,
    db_path: Path = _DB_PATH,
    output_dir: Path = report.OUTPUT_DIR,
    sources: Sequence[Source] | None = None,
    language_model: LanguageModel | None = None,
) -> Path:
    """Baut einen echten Lauf zusammen, führt ihn aus und gibt den Pfad des Reports zurück.

    Ohne `sources` und `language_model` gelten die eingebauten Quellen aus `config_path`
    und Haiku von Anthropic; wer sie angibt, ersetzt sie, dann fragt der Lauf weder das
    Netz noch das echte Sprachmodell.
    """
    config = load_config(config_path)
    if sources is None:
        sources = default_sources(config)
    if language_model is None:
        language_model = AnthropicLanguageModel(_ASSESSMENT_MODEL)
    search_profile = read_search_profile(profile_path)

    with Store(db_path) as db:
        return run(
            sources=sources,
            language_model=language_model,
            search_profile=search_profile,
            db=db,
            config=config,
            today=date.today(),
            output_dir=output_dir,
        )


# Fehler, die nicht eine Quelle oder Anzeige betreffen, sondern den ganzen Lauf abbrechen.
_ABORTS = (ConfigError, SearchProfileError, StoreError, ReportError)
_ABORTED_LOG = "abgebrochen.log"


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


def demo_run(output_dir: Path | None = None) -> str:
    """Baut einen Demo-Lauf aus den Demo-Teilen zusammen und liefert den Report-Text.

    Datenbank und Report liegen in einem temporären Ordner, der danach verschwindet;
    nur mit `output_dir` bleibt der Report zusätzlich dort als Datei liegen.
    """
    today = date.today()
    with tempfile.TemporaryDirectory(prefix="jobagent-demo-") as temp:
        with Store(Path(temp) / "demo.db") as db:
            demo.create_applications(db, today)
            path = run(
                sources=demo.sources(),
                language_model=demo.DemoLanguageModel(),
                search_profile=demo.SEARCH_PROFILE,
                db=db,
                config=demo.CONFIG,
                today=today,
                output_dir=output_dir or Path(temp),
            )
        return path.read_text(encoding="utf-8")


def cli(argv: list[str] | None = None) -> int:
    """Kommandozeile: ein echter Lauf oder mit `--demo` ein Demo-Lauf; gibt den Exit-Code zurück.

    Bricht der ganze Lauf ab, steht eine Meldung auf stderr und der Traceback nur im Log.
    """
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

    setup_logging()
    if args.demo:  # ohne Log-Datei: Der Demo-Lauf hinterlässt nichts außer dem Report
        try:
            _write_utf8(demo_run(args.output))
        except _ABORTS as error:
            return _abort(error)
        return 0

    return _real_run()


def _real_run() -> int:
    """Ein echter Lauf mit Log-Datei: benannt wie der Report, ohne Report `abgebrochen.log`."""
    report_path: Path | None = None
    run_log = RunLog()
    try:
        with run_log:
            try:
                report_path = main()
            except _ABORTS as error:
                return _abort(error)
            except BaseException:
                logger.debug("Unerwartet abgebrochen", exc_info=True)
                raise
    finally:
        # Ohne Report gibt es keinen Namen für die Log-Datei; abgebrochene Läufe
        # sammeln sich deshalb in einer eigenen.
        if report_path is None:
            run_log.save(report.OUTPUT_DIR / _ABORTED_LOG, append=True)
        else:
            run_log.save(report_path.with_suffix(".log"))
    return 0


def _abort(error: Exception) -> int:
    # DEBUG, damit der Traceback nicht neben der Meldung auf der Konsole steht; die
    # Log-Datei eines Laufs schreibt ihn mit.
    logger.debug("Abgebrochen", exc_info=True)
    print(f"Fehler: {error}", file=sys.stderr)
    return 1


def _write_utf8(text: str) -> None:
    # Die Windows-Konsole nutzt sonst eine Codepage, in der Umlaute kaputtgehen.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    raise SystemExit(cli())
