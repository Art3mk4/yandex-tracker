"""parse_rows / parse_timesheet: разбор таблицы «Записи» табеля."""
from datetime import date
from pathlib import Path

from timesheet_to_tracker import parse_rows, parse_timesheet

TIMESHEET = """# Табель

## Записи

| Дата | Задача | Часы | Что сделано | Источник |
|---|---|---|---|---|
| Чт 24.09.2026 | KEY-100 | 4.50 | Онбординг: `CLAUDE.md`, дейли | оценка → 8 ч, в Трекере |
| Чт 24.09.2026 | KEY-200 | 3.50 | Импорт из XLSX | оценка, не в Трекере |
| Вт 29.09.2026 | — (учёт времени) | 1.25 | TIMESHEET.md, скрипты | оценка, не в Трекере |
| Ср 30.09.2026 | KEY-100 | 8 | Полный день без дробной части | оценка, в Трекере |

## Итоги по дням
"""


def write(tmp_path: Path) -> Path:
    p = tmp_path / "TIMESHEET.md"
    p.write_text(TIMESHEET, encoding="utf-8")
    return p


def test_parse_rows_all_rows(tmp_path):
    rows = parse_rows(write(tmp_path))
    assert len(rows) == 4
    first = rows[0]
    assert first["date"] == date(2026, 9, 24)
    assert first["task"] == "KEY-100"
    assert first["label"] is None
    assert first["hours"] == 4.5
    assert "CLAUDE.md" in first["comment"]  # бэктики вычищены
    assert "`" not in first["comment"]


def test_parse_rows_row_without_task(tmp_path):
    rows = parse_rows(write(tmp_path))
    no_task = rows[2]
    assert no_task["task"] is None
    assert no_task["label"] == "— (учёт времени)"
    assert no_task["hours"] == 1.25


def test_parse_rows_integer_hours(tmp_path):
    rows = parse_rows(write(tmp_path))
    assert rows[3]["hours"] == 8.0


def test_parse_timesheet_filters_for_tracker(tmp_path):
    rows = parse_timesheet(write(tmp_path))
    # «не в Трекере» и строки без ID задачи не переносятся
    assert [r["task"] for r in rows] == ["KEY-100", "KEY-100"]
    assert all("не в Трекере" not in r["source"] for r in rows)
    assert sum(r["hours"] for r in rows) == 12.5
