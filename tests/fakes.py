"""Gemeinsame Fakes für Tests: `from tests.fakes import FakeLanguageModel`."""

from dataclasses import dataclass

from jobagent.language_model import LanguageModelError, with_required_keys


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
