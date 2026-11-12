"""Prüft, dass die echte Uhr nur an den Einstiegspunkten gelesen wird (CODING_STANDARDS.md).

Wer `date.today()`, `datetime.now()` oder `time.time()` mitten im Code aufruft, macht ihn
abhängig vom Tag, an dem er läuft; Tests mit echter Uhr können an bestimmten Tagen kippen.
Erlaubt sind deshalb nur:
- in `src/` die Einstiegspunkte der Kommandos, die das Datum hereinholen und weitergeben
  (`ENTRY_POINTS`); eine Referenz ohne Aufruf (`now=time.time` als Standardwert) ist
  ohnehin keine Lesestelle;
- in `tests/` nur `conftest.py`, wo die feste Uhr als Fixture liegt (`fixed_today`).
"""

import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CLOCK_CALLS = {("date", "today"), ("datetime", "now"), ("datetime", "today"), ("time", "time")}

# Datei relativ zu src/jobagent -> Funktionen, die die Uhr lesen dürfen.
ENTRY_POINTS = {
    "main.py": {"main", "demo_run"},
    "feedback.py": {"main"},
    "profile_suggestion.py": {"main"},
}

ALLOWED_TEST_FILES = {"conftest.py"}


@dataclass(frozen=True)
class ClockCall:
    path: str
    line: int
    call: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.call}()"


def clock_calls(source: str, path: str, allowed_functions: set[str]) -> list[ClockCall]:
    """Alle Aufrufe der echten Uhr außerhalb der erlaubten Funktionen."""
    found: list[ClockCall] = []

    def visit(node: ast.AST, function: str | None) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            function = node.name if function is None else function
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and (node.func.value.id, node.func.attr) in CLOCK_CALLS
            and function not in allowed_functions
        ):
            found.append(ClockCall(path, node.lineno, f"{node.func.value.id}.{node.func.attr}"))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(ast.parse(source), None)
    return found


def _repo_clock_calls() -> list[ClockCall]:
    found: list[ClockCall] = []
    package = ROOT / "src" / "jobagent"
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        source = path.read_text(encoding="utf-8")
        found += clock_calls(source, f"src/jobagent/{relative}", ENTRY_POINTS.get(relative, set()))
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path.name in ALLOWED_TEST_FILES:
            continue
        source = path.read_text(encoding="utf-8")
        found += clock_calls(source, path.relative_to(ROOT).as_posix(), set())
    return found


def test_real_clock_is_read_only_at_entry_points() -> None:
    found = _repo_clock_calls()
    assert not found, "Echte Uhr außerhalb der Einstiegspunkte:\n" + "\n".join(map(str, found))


def test_reports_clock_call_with_file_and_line() -> None:
    source = "from datetime import date\n\ndef f():\n    return date.today()\n"

    assert clock_calls(source, "x.py", set()) == [ClockCall("x.py", 4, "date.today")]


def test_finds_all_clock_calls() -> None:
    source = "a = datetime.now()\nb = datetime.today()\nc = time.time()\n"

    calls = [found.call for found in clock_calls(source, "x.py", set())]

    assert calls == ["datetime.now", "datetime.today", "time.time"]


def test_allows_clock_call_inside_entry_point_and_its_inner_functions() -> None:
    source = "def main():\n    def inner():\n        return date.today()\n    return date.today()\n"

    assert clock_calls(source, "x.py", {"main"}) == []


def test_reference_without_call_is_not_a_clock_read() -> None:
    source = "def f(now=time.time):\n    return now()\n"

    assert clock_calls(source, "x.py", set()) == []
