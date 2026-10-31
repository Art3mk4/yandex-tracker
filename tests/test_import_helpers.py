"""Хелперы импорта табеля: tracker_state, load_projects."""
import json
from datetime import date

import pytest

from app.import_timesheet import load_projects, tracker_state


def test_tracker_state_order_matters():
    # «не в Трекере» содержит подстроку «в Трекере» — проверяется первым
    assert tracker_state("оценка, не в Трекере") == "excluded"
    assert tracker_state("оценка → 8 ч, в Трекере") == "synced"
    assert tracker_state("оценка") == "pending"


def test_load_projects_missing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        load_projects()
    assert "projects.json" in str(e.value)


def test_load_projects_empty_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "projects.json").write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_projects()


def test_load_projects_valid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "projects.json").write_text(json.dumps([
        {"code": "my-project", "sessions_path": "~/.claude/projects/x", "since": "2026-09-24"},
    ]), encoding="utf-8")
    assert load_projects() == [("my-project", "~/.claude/projects/x", date(2026, 9, 24))]
