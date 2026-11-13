"""Дедуп REST-режима (plan_actions, duration_to_minutes) — без сети и токена."""
from timesheet_to_tracker import duration_to_minutes, local_date, plan_actions


def wl(id_, display, start, duration):
    """Ворклог как в ответе GET /issues/<task>/worklog (создатель — в createdBy)."""
    return {"id": id_, "createdBy": {"display": display}, "start": start, "duration": duration}


def entry(task="KEY-1", date="2026-11-06", duration="PT8H"):
    return {
        "task": task,
        "date": date,
        "start": f"{date}T18:00:00.000+0300",
        "duration": duration,
        "comment": "тест",
    }


def test_no_worklogs_creates():
    [res] = plan_actions([entry()], {}, "me")
    assert res == {"task": "KEY-1", "date": "2026-11-06", "to": "PT8H", "action": "create"}


def test_same_duration_in_minutes_even_as_p1d():
    # сервер сворачивает 8 ч в P1D — сравнение в минутах, а не строками
    worklogs = {"KEY-1": [wl(1, "me", "2026-11-06T12:00:00.000+0000", "P1D")]}
    [res] = plan_actions([entry()], worklogs, "me")
    assert res["action"] == "same"


def test_foreign_author_creates():
    worklogs = {"KEY-1": [wl(1, "other", "2026-11-06T12:00:00.000+0000", "PT8H")]}
    [res] = plan_actions([entry()], worklogs, "me")
    assert res["action"] == "create"


def test_foreign_date_creates():
    worklogs = {"KEY-1": [wl(1, "me", "2026-11-05T12:00:00.000+0000", "PT8H")]}
    [res] = plan_actions([entry()], worklogs, "me")
    assert res["action"] == "create"


def test_missing_created_by_ignored():
    worklogs = {"KEY-1": [{"id": 1, "start": "2026-11-06T12:00:00.000+0000", "duration": "PT8H"}]}
    [res] = plan_actions([entry()], worklogs, "me")
    assert res["action"] == "create"


def test_different_duration_updates_first_own():
    worklogs = {
        "KEY-1": [
            wl(7, "other", "2026-11-06T08:00:00.000+0000", "PT1H"),
            wl(9, "me", "2026-11-06T09:00:00.000+0000", "PT6H"),
            wl(10, "me", "2026-11-06T13:00:00.000+0000", "PT2H"),
        ]
    }
    [res] = plan_actions([entry()], worklogs, "me")
    assert res["action"] == "update"
    assert (res["from"], res["id"], res["to"]) == ("PT6H", 9, "PT8H")


def test_duration_to_minutes():
    assert duration_to_minutes("PT8H") == 480
    assert duration_to_minutes("P1D") == 480  # рабочий день
    assert duration_to_minutes("PT4H45M") == 285
    assert duration_to_minutes("P2D") == 960
    assert duration_to_minutes("P1W") == 2400


def test_local_date_parses_zone_and_keeps_day():
    # сервер отдаёт start в UTC («+0000») — полдень не должен уехать в соседний день
    assert local_date("2026-11-06T12:00:00.000+0000") == "2026-11-06"
    # время без зоны трактуем как UTC, а не оставляем naive-дату как есть
    assert local_date("2026-11-06T12:00:00") == "2026-11-06"
