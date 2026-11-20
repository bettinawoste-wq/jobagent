"""Demo-Set für den Demo-Lauf: erfundene Anzeigen, vorgefertigte Bewertungen, Demo-Konfiguration.

Alles hier ist synthetisch und öffentlich: nur erkennbar erfundene Firmen, Links auf
example.com. Die Bewertungen sind so geschrieben, als kämen sie vom Modell gegen das
Demo-Suchprofil `SEARCH_PROFILE`, einen Auszug aus `profile.example.md`. Das
Demo-Sprachmodell gibt sie als Antworten zurück, damit sie dieselbe Prüfung durchlaufen
wie echte Antworten. Ein Demo-Lauf holt nichts aus dem Netz, fragt kein echtes
Sprachmodell und liest oder speichert nichts Persönliches.
"""

from datetime import date, timedelta

from jobagent import store
from jobagent.config import Config
from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModelError, with_required_keys
from jobagent.position import position_key
from jobagent.score import Assessment, job_ad_as_text
from jobagent.sources import SearchResult, Source
from jobagent.store import Store

CONFIG = Config(
    keywords=["Full-Stack-Entwickler", "IT Consultant", "Embedded Entwickler", "Data Scientist"],
    published_since=7,
    min_score=3,
    follow_up_min_days=14,
    follow_up_max_days=28,
)

SEARCH_PROFILE = """# Suchprofil (Demo)

## Gesuchte Rollen
1. Full-Stack-Entwicklung (z.B. Python, JavaScript, C++)
2. IT Consultant (technische Beratung/Implementierung, Anforderungsanalyse)
3. Embedded C/C++/Qt oder DevOps/Linux, wenn der Rest passt
4. Data Science / Data Analytics

## Ort und Arbeitsmodell
- Beispielstadt und Umgebung (Umkreis ca. 30 km)
- Hybrid oder Remote bevorzugt, vollständig vor Ort nur bei sehr gutem Match
"""

_LINK = "https://example.com/stellen/"


def _job_ad(id_: str, title: str, company: str, location: str, description: str) -> JobAd:
    return JobAd(id_, title, company, location, f"{_LINK}{id_}", description)


# Je Quelle: Suchbegriff -> Anzeigen, die diese Demo-Quelle dafür "findet".
_BUNDESAGENTUR = {
    "Full-Stack-Entwickler": [
        _job_ad(
            "demo-ba-1",
            "Full-Stack-Entwickler (m/w/d) Python/TypeScript",
            "Fiktiva Software GmbH",
            "Beispielstadt",
            "Wir entwickeln Webanwendungen mit Python, FastAPI und React. Hybrid, 2 Tage Büro.",
        ),
    ],
    "IT Consultant": [
        _job_ad(
            "demo-ba-2",
            "IT Consultant (m/w/d) Prozessdigitalisierung",
            "Exempla Consulting GmbH",
            "Beispielstadt",
            "Beratung von Mittelständlern bei der Digitalisierung, viel Kundenkontakt vor Ort.",
        ),
    ],
    "Embedded Entwickler": [
        _job_ad(
            "demo-ba-3",
            "Embedded-Softwareentwickler C++/Qt (m/w/d)",
            "Platzhalter Systems AG",
            "Musterhausen",
            "Steuerungssoftware für Messgeräte in C++ und Qt, vollständig vor Ort.",
        ),
    ],
}

_ARBEITNOW = {
    "Full-Stack-Entwickler": [
        _job_ad(
            "demo-an-1",
            "Python Developer (w/m/d)",
            "Beispiel Tech",
            "Remote",
            "Backend mit Python und PostgreSQL, Remote in Deutschland, neu: Kubernetes-Erfahrung.",
        ),
    ],
    "Data Scientist": [
        _job_ad(
            "demo-an-2",
            "Data Scientist (m/w/d)",
            "Lorem Data GmbH",
            "Remote",
            "Prognosemodelle mit Python, pandas und scikit-learn, Remote mit Teamtreffen.",
        ),
    ],
    "IT Consultant": [
        _job_ad(
            "demo-an-3",
            "SAP-Berater FI/CO (m/w/d)",
            "Musterfirma Beratung GmbH",
            "Beispielstadt",
            "Einführung von SAP S/4HANA im Finanzwesen, 80 % Reisetätigkeit.",
        ),
    ],
}

_WATCHLIST = {
    "Full-Stack-Entwickler": [
        _job_ad(
            "demo-wl-1",
            "DevOps Engineer (m/w/d)",
            "Testfeld Robotics GmbH",
            "Beispielstadt",
            "CI/CD, Linux und Container für unsere Roboterflotte, Hybrid.",
        ),
    ],
    "Data Scientist": [
        _job_ad(
            "demo-wl-2",
            "Werkstudent Data Analytics (m/w/d)",
            "Testfeld Robotics GmbH",
            "Beispielstadt",
            "Werkstudentenstelle, 20 Stunden pro Woche, Auswertungen mit SQL und Python.",
        ),
    ],
}
_EARLIER_JOB_AD = _job_ad(
    "demo-ba-alt",
    "Python Developer (m/w/d)",
    "Beispiel Tech GmbH",
    "Remote",
    "Backend mit Python und PostgreSQL, Remote in Deutschland.",
)

_WATCHLIST_ERROR = "Musterwerk AG: Board nicht erreichbar"

ASSESSMENTS: dict[str, Assessment] = {
    "demo-ba-1": Assessment(
        5,
        ["Python und JavaScript/TypeScript", "Full-Stack wie gesucht", "Hybrid in Beispielstadt"],
        [],
        [],
        "Sehr guter Match für die erste Wunschrolle.",
    ),
    "demo-an-1": Assessment(
        4,
        ["Python, SQL", "Remote"],
        [],
        ["Kubernetes"],
        "Passt gut, Kubernetes wäre neu.",
    ),
    "demo-an-2": Assessment(
        4,
        ["Data Science mit Python", "Remote"],
        [],
        ["scikit-learn nur in Grundzügen"],
        "Gute Passung zur vierten Wunschrolle.",
    ),
    "demo-ba-2": Assessment(
        3,
        ["IT Consultant als Wunschrolle", "Anforderungsanalyse"],
        ["Viel Präsenz beim Kunden"],
        [],
        "Rolle passt, Arbeitsmodell nur teilweise.",
    ),
    "demo-ba-3": Assessment(
        3,
        ["C++ und Qt"],
        ["Vollständig vor Ort", "Musterhausen liegt am Rand des Umkreises"],
        [],
        "Technisch passend, Arbeitsmodell schwächer.",
    ),
    "demo-wl-1": Assessment(
        3,
        ["Linux, CI/CD", "Hybrid"],
        [],
        ["Container-Orchestrierung"],
        "Solide Alternative in Richtung DevOps.",
    ),
    "demo-wl-2": Assessment(
        2,
        ["SQL und Python"],
        ["Werkstudentenstelle trotz Berufserfahrung"],
        [],
        "Inhaltlich nah, aber falsches Level.",
    ),
    "demo-an-3": Assessment(
        1,
        [],
        ["80 % Reisetätigkeit"],
        ["SAP FI/CO"],
        "Fachfremd und kaum vereinbar mit dem Arbeitsmodell.",
    ),
}


class DemoSource:
    """Quelle am Interface `Source`, die je Suchbegriff erfundene Anzeigen "findet"."""

    def __init__(
        self, name: str, job_ads: dict[str, list[JobAd]], errors: list[str] | None = None
    ) -> None:
        self.name = name
        self._job_ads = job_ads
        self._errors = list(errors or [])

    def search(self, keywords: list[str]) -> SearchResult:
        found: dict[str, JobAd] = {}
        for keyword in keywords:
            for job_ad in self._job_ads.get(keyword, []):
                found.setdefault(job_ad.id, job_ad)
        return SearchResult(list(found.values()), list(self._errors))


def sources() -> list[Source]:
    """Drei Demo-Quellen, benannt wie die echten; die Firmen-Watchlist meldet einen Fehler."""
    return [
        DemoSource("Bundesagentur für Arbeit (Demo)", _BUNDESAGENTUR),
        DemoSource("Arbeitnow (Demo)", _ARBEITNOW),
        DemoSource("Firmen-Watchlist (Demo)", _WATCHLIST, [_WATCHLIST_ERROR]),
    ]


class DemoLanguageModel:
    """Sprachmodell am Seam `LanguageModel`, das für jede Demo-Anzeige eine vorgefertigte
    Bewertung antwortet, statt ein echtes Sprachmodell zu fragen.

    Die Anzeige erkennt es am Ende der Anfrage, wo die Bewertung sie als Text anhängt.
    Für eine andere Anzeige hat es keine Antwort; fehlt einer Demo-Anzeige ihre
    vorgefertigte Bewertung, scheitert schon der Aufbau.
    """

    def __init__(self) -> None:
        self._answers = {
            job_ad_as_text(job_ad): ASSESSMENTS[job_ad.id].as_model_answer()
            for source in sources()
            for job_ad in source.search(CONFIG.keywords).job_ads
        }

    def ask(self, system: str, text: str, schema: dict) -> dict:
        answer = next(
            (answer for job_ad, answer in self._answers.items() if text.endswith(job_ad)), None
        )
        if answer is None:
            raise LanguageModelError("Keine vorgefertigte Bewertung für diese Anzeige")
        return with_required_keys(schema, dict(answer))


def create_applications(db: Store, today: date) -> None:
    """Legt die Bewerbungen an, die es vor dem Demo-Lauf schon gibt (Datum relativ zu heute)."""
    # Ohne Antwort und im Nachfass-Fenster: erscheint als Nachfass-Hinweis.
    db.create_application(
        store.NewApplication(
            position_key("Datenwerk Muster GmbH", "Data Engineer (m/w/d)"),
            "Datenwerk Muster GmbH",
            "Data Engineer (m/w/d)",
            None,
        ),
        store.ApplicationStatus.APPLIED,
        today - timedelta(days=18),
    )

    # Bewerbung auf eine frühere Anzeige derselben Stelle: Die neue Anzeige von Arbeitnow
    # (demo-an-1) schreibt Firma und Titel anders und hat einen anderen Text.
    applied_on = today - timedelta(days=35)
    db.remember_job_ad(_EARLIER_JOB_AD, ASSESSMENTS["demo-an-1"], applied_on)
    db.create_application(
        store.NewApplication(
            position_key(_EARLIER_JOB_AD.company, _EARLIER_JOB_AD.title),
            _EARLIER_JOB_AD.company,
            _EARLIER_JOB_AD.title,
            _EARLIER_JOB_AD.id,
        ),
        store.ApplicationStatus.INTERVIEW,
        applied_on,
    )
