"""entry_where: сборка фильтров табеля (параметры и число условий)."""
from datetime import date

from app.api import EntryFilters, entry_where


def test_no_filters():
    where, params = entry_where(EntryFilters())
    assert params == {}
    assert not str(where).strip() or where.as_string is not None  # пустое WHERE


def test_all_filters():
    f = EntryFilters(
        date_from=date(2026, 9, 24), date_to=date(2026, 10, 30),
        project_id=2, queue="BACKEND", task="507", state="synced",
    )
    where, params = entry_where(f)
    assert params == {
        "date_from": date(2026, 9, 24), "date_to": date(2026, 10, 30),
        "project_id": 2, "queue": "BACKEND", "task_like": "%507%", "state": "synced",
    }


def test_task_search_wraps_wildcards():
    _, params = entry_where(EntryFilters(task="рол"))
    assert params["task_like"] == "%рол%"
