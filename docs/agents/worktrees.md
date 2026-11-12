# Ablauf für Implementer-Agenten

Diese Datei gilt für jeden Agenten, der in einem eigenen Worktree ein Ticket umsetzt und seine Arbeit in einen Integrations-Branch zurückgibt, zum Beispiel unter `/implement-spec`. Dein Auftrag nennt nur das Ticket und den Integrations-Branch. Alles andere steht hier.

## 1. Auf den Integrations-Branch setzen
Ein neuer Agent-Worktree startet auf `master`, nicht auf dem Integrations-Branch. Setze deinen Branch auf dessen Spitze. Für Integrations-Branches unter `claude/` ist das freigegeben (`.claude/settings.json`):

```bash
git reset --hard claude/<integrations-branch>
```

Liegt der Integrations-Branch woanders, geht `git checkout -B <eigener-branch> <integrations-branch>`. Prüfe das Ergebnis mit `git merge-base --is-ancestor <integrations-branch> HEAD`.

## 2. Bauen
- Lies dein Ticket mit `gh issue view <n> -R bettinawoste-wq/jobagent`. Lies außerdem die Doku, auf die `CLAUDE.md` für deinen Bereich verweist.
- Baue mit dem Skill `mattpocock-skills:tdd`. Die Seams und das Verhalten stehen im Ticket, du stimmst sie nicht vorher noch einmal ab.
- Bleib im Umfang des Tickets. Was dir außerhalb auffällt, gehört in den Bericht.

## 3. Committen
- Es gelten die Regeln in `CLAUDE.md`: Betreff deutsch, im Imperativ, mit echten Umlauten. Der Text erklärt das Warum. Dazu `Refs #<n>` und am Ende `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Gib auch Merge-Commits einen deutschen Text: `git merge <integrations-branch> -m "Merge <integrations-branch>: <worum es geht>"`.
- Die Version hebst du nicht an. Das macht die Sitzung, die integriert, wenn die zusammenhängende Arbeit fertig ist.

## 4. Vor dem Bericht
- Lass alle Prüfungen wie in der CI laufen: `uv run ruff check .`, `uv run ruff format --check .` und `uv run pytest`.
- Ob der Demo-Lauf zeichengleich ausgibt, prüft `tests/test_demo_snapshot.py` gegen den Snapshot `tests/fixtures/demo_report.md`. Vergleiche nicht per Hand. Ändert das Ticket den Report gewollt, schreib den Snapshot mit `JOBAGENT_UPDATE_SNAPSHOT=1 uv run pytest tests/test_demo_snapshot.py` neu und committe seinen Diff mit.
- Merge die aktuelle Spitze des Integrations-Branch in deinen Branch und lass die Prüfungen danach noch einmal laufen.
- Push nichts und schließ keine Issues. Beides macht die Sitzung, die integriert (`docs/agents/issue-tracker.md`).

## 5. Bericht
Kurz und auf Deutsch:
- Branch und Commits
- ein Satz zum Ergebnis
- Anzahl der Tests und ob sie grün sind
- was dir außerhalb des Tickets aufgefallen ist
