"""Prüft, dass Bezeichner englisch sind (ADR 0005).

Geprüft werden die Namen, die der Code selbst vergibt: Module, Klassen, Funktionen,
Parameter, Variablen, Felder und Testnamen. Strings bleiben außen vor, damit die
deutschen Schlüssel an den Übersetzungsstellen (Konfiguration, Datenbank,
Bewertungs-Schlüssel der Modelle) und fremde Feldnamen erlaubt bleiben.

Bewusst nicht geprüft werden Namen, die anderswo vergeben oder nur selten sind:
- Schlüsselwort-Argumente in Aufrufen (`f(anzeige=1)`): Der Name gehört dem
  aufgerufenen Code und wird bei dessen Parametern geprüft.
- Importierte Namen ohne `as`: Sie gehören dem importierten Modul.
- Captures in `match`/`case` (`case {"x": wert}`) und Typparameter (`def f[T]()`).
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Deutsche Wortstämme aus dem Glossar und häufige deutsche Programmierwörter.
# Ein Wortteil eines Namens wird gemeldet, wenn er mit einem dieser Stämme beginnt.
GERMAN_STEMS = (
    # Glossar
    "anzeige",
    "stelle",
    "treffer",
    "bewert",
    "bewerb",
    "quelle",
    "lauf",
    "profil",
    "rueckmeld",
    # Programmierwörter
    "daten",
    "fehler",
    "ergebnis",
    "eintrag",
    "antwort",
    "pfad",
    "wert",
    "heute",
    "jetzt",
    "suche",
    "konfig",
)

# Englische Wortteile, die mit einem deutschen Stamm beginnen. Als ganze Wortteile
# gelistet statt über eine Endung erkannt, damit "profil" selbst gemeldet bleibt.
ALLOWED_PARTS = {
    "profile",
    "profiles",
    "profiled",
    "profiler",
    "profilers",
    "profiling",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    name: str
    part: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: Bezeichner '{self.name}' enthält '{self.part}'"


def name_parts(name: str) -> list[str]:
    """Zerlegt einen Namen in snake_case- und CamelCase-Wortteile, kleingeschrieben."""
    parts = []
    for chunk in name.split("_"):
        parts += re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", chunk)
    return [part.lower() for part in parts]


def german_part(name: str) -> str | None:
    for part in name_parts(name):
        if part in ALLOWED_PARTS:
            continue
        if any(part.startswith(stem) for stem in GERMAN_STEMS):
            return part
    return None


def defined_names(tree: ast.AST) -> list[tuple[str, int]]:
    """Alle Namen, die der Code vergibt, mit ihrer Zeile."""
    names = []
    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.append((node.name, node.lineno))
            case ast.arg():
                names.append((node.arg, node.lineno))
            case ast.Name(ctx=ast.Store()):
                names.append((node.id, node.lineno))
            case ast.Attribute(ctx=ast.Store()):
                names.append((node.attr, node.lineno))
            case ast.ExceptHandler(name=str()):
                names.append((node.name, node.lineno))
            case ast.alias(asname=str()):
                names.append((node.asname, node.lineno))
    return names


def find_german_identifiers(source: str, path: str) -> list[Finding]:
    findings = []
    for name, line in defined_names(ast.parse(source)):
        part = german_part(name)
        if part:
            findings.append(Finding(path, line, name, part))
    return findings


def find_german_module(path: Path) -> list[Finding]:
    findings = []
    for name in [*path.relative_to(ROOT).parent.parts, path.stem]:
        part = german_part(name)
        if part:
            findings.append(Finding(path.relative_to(ROOT).as_posix(), 1, name, part))
    return findings


def python_files() -> list[Path]:
    return sorted([*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py")])


def test_identifiers_in_code_and_tests_are_english():
    findings = []
    for path in python_files():
        findings += find_german_module(path)
        relative = path.relative_to(ROOT).as_posix()
        findings += find_german_identifiers(path.read_text(encoding="utf-8"), relative)

    assert not findings, "Deutsche Bezeichner (ADR 0005):\n" + "\n".join(map(str, findings))


def test_german_variable_is_reported_with_file_line_and_part():
    source = "x = 1\nanzeige = 2\n"

    findings = find_german_identifiers(source, "beispiel.py")

    assert [str(f) for f in findings] == ["beispiel.py:2: Bezeichner 'anzeige' enthält 'anzeige'"]


def test_parts_of_snake_and_camel_case_names_are_checked():
    source = (
        "class JobTrefferList:\n"
        "    def load(self, raw_daten):\n"
        "        self.last_fehler = None\n"
        "def test_bewertung_is_saved():\n"
        "    pass\n"
    )

    findings = find_german_identifiers(source, "beispiel.py")

    assert [(f.line, f.name, f.part) for f in findings] == [
        (1, "JobTrefferList", "treffer"),
        (4, "test_bewertung_is_saved", "bewertung"),
        (2, "raw_daten", "daten"),
        (3, "last_fehler", "fehler"),
    ]


def test_english_words_containing_a_german_stem_are_not_reported():
    source = "unprofiled = 1\nprofile = 2\nwatchlist_source = 3\ndef convert_date(): pass\n"

    assert find_german_identifiers(source, "beispiel.py") == []


def test_english_words_of_the_profile_family_are_not_reported():
    source = "profiler = 1\nprofiling = 2\ndef profiled_run(): pass\nclass Profilers: pass\n"

    assert find_german_identifiers(source, "beispiel.py") == []


def test_german_profile_words_are_still_reported():
    source = "profil = 1\nprofil_vorschlag = 2\n"

    findings = find_german_identifiers(source, "beispiel.py")

    assert [(f.name, f.part) for f in findings] == [
        ("profil", "profil"),
        ("profil_vorschlag", "profil"),
    ]


def test_strings_with_german_keys_are_not_reported():
    source = 'assessment = {"score": 3, "passt_nicht": [], "luecken": []}\nkey = "anzeige_daten"\n'

    assert find_german_identifiers(source, "beispiel.py") == []


def test_german_module_name_is_reported():
    findings = find_german_module(ROOT / "src" / "jobagent" / "profilvorschlag.py")

    assert [(f.name, f.part) for f in findings] == [("profilvorschlag", "profilvorschlag")]
