"""MCP-сервер «timesheet»: чтение табеля и зеркала Трекера из Postgres для AI-агентов.

Монтируется в FastAPI-приложение (app/main.py) — конечная точка
streamable-http: /mcp/mcp. Зеркало — резерв на недоступность Яндекс Трекера.
"""
import re
from datetime import datetime

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from app import mirror
from app.config import settings
from app.db import connect

mcp = FastMCP("timesheet")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@mcp.tool
def entries_for_day(date: str) -> dict:
    """Записи табеля за день.

    date — день в формате YYYY-MM-DD. Возвращает записи (задача, часы,
    что сделано, состояние в Трекере, проект) и сумму часов за день.
    """
    if not DATE_RE.match(date):
        raise ToolError("date должен быть в формате YYYY-MM-DD")
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError as e:
        raise ToolError(f"date — несуществующая дата: {e}") from e

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT e.task_key, e.label, e.hours, e.description, e.tracker_state,
                      p.code AS project
               FROM time_entries e LEFT JOIN projects p ON p.id = e.project_id
               WHERE e.work_date = %s
               ORDER BY e.task_key NULLS LAST""",
            (day,),
        )
        rows = cur.fetchall()
    entries = [
        {
            "task": r["task_key"],
            "label": r["label"],
            "hours": float(r["hours"]),
            "description": r["description"],
            "tracker_state": r["tracker_state"],
            "project": r["project"],
        }
        for r in rows
    ]
    return {
        "date": date,
        "entries": entries,
        "entries_count": len(entries),
        "total_hours": sum(e["hours"] for e in entries),
    }


@mcp.tool
def search_issues(query: str = "", queue: str = "") -> dict:
    """Поиск задач в локальном зеркале Трекера.

    query — подстрока в названии или описании; queue — очередь (BACKEND, FRONTEND…).
    Возвращает до 20 задач (ключ, название, статус, очередь, обновлена) и total.
    Зеркало синхронизируется командой tracker_sync; содержит задачи пользователя
    и задачи из табеля.
    """
    with connect() as conn:
        rows = mirror.search_issues(conn, query or None, queue or None, None)
    items = [
        {
            "key": r["key"], "summary": r["summary"], "queue": r["queue"],
            "status": r["status_name"], "assignee": r["assignee_name"],
            "updated_at": r["updated_at"], "comments": r["comments_count"],
            "attachments": r["attachments_count"],
        }
        for r in rows[:20]
    ]
    return {"total": len(rows), "issues": items}


@mcp.tool
def get_issue(key: str) -> dict:
    """Задача из локального зеркала Трекера: карточка, комментарии, вложения, история.

    key — ключ задачи (работает и старый ключ-алиас, например старый ключ после переноса задачи в другую очередь).
    Возвращает описание, все комментарии, вложения (имя, размер, URL скачивания)
    и историю изменений.
    """
    with connect() as conn:
        data = mirror.get_issue(conn, key)
    if not data:
        raise ToolError(f"Задачи {key} нет в зеркале")
    issue = data["issue"]
    return {
        "key": issue["key"],
        "summary": issue["summary"],
        "description": issue["description"],
        "status": issue["status_name"],
        "queue": issue["queue"],
        "assignee": issue["assignee_name"],
        "created_at": issue["created_at"],
        "updated_at": issue["updated_at"],
        "aliases": issue["aliases"],
        "comments": [
            {"author": c["author_name"], "created_at": c["created_at"], "text": c["text"]}
            for c in data["comments"]
        ],
        "attachments": [
            {
                "name": a["name"], "size": a["size"],
                "url": f"{settings.public_base_url}{a['url']}" if a["url"] else None,
            }
            for a in data["attachments"]
        ],
        "changelog": data["changelog"][-20:],  # последние 20 изменений
    }
