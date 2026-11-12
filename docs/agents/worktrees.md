# Worktrees für Implementer-Agenten

Diese Datei gilt für jeden Agenten, der in einem eigenen Worktree an einem Ticket arbeitet und seine Arbeit in einen Integrations-Branch zurückgibt, zum Beispiel unter `/implement-spec`.

## Auf den Integrations-Branch setzen
Ein neuer Agent-Worktree startet auf `master`, nicht auf dem Integrations-Branch. Setze deinen Branch auf dessen Spitze. Freigegeben ist das für Integrations-Branches unter `claude/` (`.claude/settings.json`):

```bash
git reset --hard claude/<integrations-branch>
```

Liegt der Integrations-Branch woanders, geht `git checkout -B <eigener-branch> <integrations-branch>`.

Prüfe das Ergebnis mit `git merge-base --is-ancestor <integrations-branch> HEAD`.

## Vor dem Bericht
- Alle Prüfungen wie in CI: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`
- Den Demo-Lauf in einem temporären Verzeichnis starten, damit im Repo kein `output/` entsteht: `uv run --project <worktree> python -m jobagent.main --demo`
- Die aktuelle Spitze des Integrations-Branch in den eigenen Branch mergen und die Prüfungen danach wiederholen
- Nicht pushen und keine Issues schließen; beides macht die Sitzung, die integriert
