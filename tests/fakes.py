"""Gemeinsame Fakes für Tests: `from tests.fakes import FakeLanguageModel`."""

from dataclasses import dataclass, field, replace
from typing import cast

import anthropic

from jobagent.job_ad import JobAd
from jobagent.language_model import LanguageModelError, with_required_keys
from jobagent.score import Assessment
from jobagent.sources import DescriptionUnavailable, SearchResult


@dataclass
class FakeSource:
    """Quelle am Interface `Source`, die feste Anzeigen und Fehler liefert.

    Sie hält in `received` die Suchbegriffe jeder Suche fest und in `described` die IDs der
    Anzeigen, die der Lauf beschreiben ließ. `descriptions` ergänzt dabei eine Beschreibung,
    `unavailable` lässt den Abruf mit diesem Grund scheitern.
    """

    job_ads: list[JobAd] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    name: str = "Bundesagentur für Arbeit"
    descriptions: dict[str, str] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)
    received: list[list[str]] = field(default_factory=list)
    described: list[str] = field(default_factory=list)

    def search(self, keywords: list[str]) -> SearchResult:
        self.received.append(keywords)
        return SearchResult(list(self.job_ads), list(self.errors), list(self.notices))

    def describe(self, job_ad: JobAd) -> JobAd:
        self.described.append(job_ad.id)
        if job_ad.id in self.unavailable:
            raise DescriptionUnavailable(self.unavailable[job_ad.id])
        if job_ad.id in self.descriptions:
            return replace(job_ad, description=self.descriptions[job_ad.id])
        return job_ad


def fake_job_ad(id_: str) -> JobAd:
    """Eine Anzeige "Stelle <id_>" der Beispiel GmbH in München."""
    return JobAd(
        id=id_,
        title=f"Stelle {id_}",
        company="Beispiel GmbH",
        location="München",
        link=f"https://example.com/{id_}",
    )


def assessment_answer(score: int = 4) -> dict:
    """Antwort des Sprachmodells auf eine Bewertung, unter den deutschen Schlüsseln."""
    return Assessment(score, ["Python"], [], [], "Passt.").as_model_answer()


@dataclass(frozen=True)
class LanguageModelRequest:
    """Eine Anfrage an das Sprachmodell, so wie der Seam sie bekommt."""

    system: str
    text: str
    schema: dict


class FakeLanguageModel:
    """Sprachmodell am Seam `LanguageModel` mit vorgegebenen Antworten; merkt sich Anfragen.

    Die Antworten gelten der Reihe nach, die letzte gilt für alle weiteren Anfragen. Ist
    eine Antwort ein `LanguageModelError`, wird er geworfen; fehlt ihr ein Pflichtschlüssel
    des Schemas, ebenso, wie beim echten Sprachmodell. Ohne Antworten darf das
    Sprachmodell gar nicht gefragt werden.
    """

    def __init__(self, *answers: dict | LanguageModelError) -> None:
        self._answers = list(answers)
        self.requests: list[LanguageModelRequest] = []

    def ask(self, system: str, text: str, schema: dict) -> dict:
        if not self._answers:
            raise AssertionError("Das Sprachmodell darf hier nicht gefragt werden")
        self.requests.append(LanguageModelRequest(system, text, schema))
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        if isinstance(answer, LanguageModelError):
            raise answer
        return with_required_keys(schema, dict(answer))


def as_anthropic(client: object) -> anthropic.Anthropic:
    """Ein nachgebauter Anthropic-Client in der Rolle des echten.

    Nachgebaut müssen nur `messages` und `beta.messages` sein, mehr nutzen die Adapter nicht.
    """
    return cast(anthropic.Anthropic, client)
