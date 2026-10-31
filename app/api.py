"""JSON API дашборда: записи, итоги, проекты + зеркало Трекера. Префикс /api.

Все списочные эндпоинты табеля принимают один набор фильтров (EntryFilters
через Depends), поэтому плитки, графики и таблица всегда показывают один срез
данных. Условия WHERE собираются psycopg.sql-композицией — без ручного
экранирования литеральных %.
"""
from dataclasses import dataclass
from datetime import date
from mimetypes import guess_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from psycopg import sql

from app import mirror
from app.config import settings
from app.db import connect

router = APIRouter(prefix="/api")


@dataclass
class EntryFilters:
    """Общие фильтры табеля (query-параметры)."""

    date_from: date | None = None
    date_to: date | None = None
    project_id: int | None = None
    queue: str | None = None
    task: str | None = None
    state: str | None = None


Filters = Annotated[EntryFilters, Depends()]


def entry_where(f: EntryFilters) -> tuple[sql.Composable, dict]:
    """WHERE для time_entries: sql-композиция + именованные параметры."""
    conds, params = [], {}
    if f.date_from:
        conds.append(sql.SQL("work_date >= ") + sql.Placeholder("date_from"))
        params["date_from"] = f.date_from
    if f.date_to:
        conds.append(sql.SQL("work_date <= ") + sql.Placeholder("date_to"))
        params["date_to"] = f.date_to
    if f.project_id:
        conds.append(sql.SQL("project_id = ") + sql.Placeholder("project_id"))
        params["project_id"] = f.project_id
    if f.queue:
        conds.append(sql.SQL("split_part(task_key, '-', 1) = ") + sql.Placeholder("queue"))
        params["queue"] = f.queue
    if f.task:
        # шаблон %…% живёт в значении параметра — литеральных % в SQL нет
        conds.append(
            sql.SQL("(task_key ILIKE ") + sql.Placeholder("task_like")
            + sql.SQL(" OR label ILIKE ") + sql.Placeholder("task_like") + sql.SQL(")"))
        params["task_like"] = f"%{f.task}%"
    if f.state:
        conds.append(sql.SQL("tracker_state = ") + sql.Placeholder("state"))
        params["state"] = f.state
    where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conds) if conds else sql.SQL("")
    return where, params


@router.get("/health")
def health() -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        ok = cur.fetchone()["ok"]
    return {"status": "ok", "db": bool(ok)}


@router.get("/meta")
def meta() -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT min(work_date) AS min_date, max(work_date) AS max_date,
                      sum(hours)::float8 AS total_hours, count(*) AS entries_count,
                      count(DISTINCT work_date) AS days_count
               FROM time_entries"""
        )
        totals = cur.fetchone()
        cur.execute(
            """SELECT split_part(task_key, '-', 1) AS queue
               FROM time_entries WHERE task_key IS NOT NULL
               GROUP BY 1 ORDER BY 1"""
        )
        queues = [r["queue"] for r in cur.fetchall()]
        cur.execute(
            "SELECT tracker_state, count(*) AS n FROM time_entries GROUP BY 1 ORDER BY 1"
        )
        states = {r["tracker_state"]: r["n"] for r in cur.fetchall()}
    return {**totals, "queues": queues, "tracker_states": states}


@router.get("/entries")
def entries(f: Filters) -> dict:
    where, params = entry_where(f)
    query = sql.SQL(
        """SELECT e.id, e.work_date, e.task_key, e.label, e.hours::float8 AS hours,
                  e.description, e.estimate_source, e.tracker_state,
                  jsonb_build_object('id', p.id, 'code', p.code) AS project
           FROM time_entries e LEFT JOIN projects p ON p.id = e.project_id"""
    ) + where + sql.SQL(" ORDER BY e.work_date DESC, e.id DESC")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return {
        "entries": rows,
        "count": len(rows),
        "total_hours": round(sum(r["hours"] for r in rows), 2) if rows else 0,
    }


@router.get("/totals/daily")
def totals_daily(f: Filters) -> dict:
    where, params = entry_where(f)
    if params:
        query = (
            sql.SQL("SELECT work_date, sum(hours)::float8 AS hours, count(*) AS entries"
                    " FROM time_entries")
            + where + sql.SQL(" GROUP BY work_date ORDER BY work_date"))
    else:
        query = sql.SQL(
            "SELECT work_date, hours::float8 AS hours, entries"
            " FROM v_daily_totals ORDER BY work_date")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        days = cur.fetchall()
    return {"days": days, "total_hours": round(sum(d["hours"] for d in days), 2) if days else 0}


@router.get("/totals/tasks")
def totals_tasks(f: Filters, top: int = Query(15, ge=1, le=50)) -> dict:
    where, params = entry_where(f)
    query = (
        sql.SQL("""SELECT COALESCE(task_key, label) AS task,
                          split_part(task_key, '-', 1) AS queue,
                          sum(hours)::float8 AS hours, count(*) AS entries
                   FROM time_entries""")
        + where + sql.SQL(" GROUP BY 1, 2 ORDER BY hours DESC, task"))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        all_tasks = cur.fetchall()
    return {
        "tasks": all_tasks[:top],
        "tasks_total": len(all_tasks),
        "total_hours": round(sum(t["hours"] for t in all_tasks), 2) if all_tasks else 0,
    }


@router.get("/projects")
def projects() -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, code, since FROM projects ORDER BY since")
        return cur.fetchall()


@router.get("/tasks/{task_key}/report")
def task_report(task_key: str) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT task, work_date, hours::float8 AS hours, description
               FROM v_task_report(%s)""",
            (task_key,),
        )
        rows = cur.fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Нет записей по {task_key}")
    return {
        "task": task_key,
        "rows": rows,
        "total_hours": round(sum(r["hours"] for r in rows), 2),
    }


# --- Зеркало Яндекс Трекера ---

@router.get("/issues")
def issues(q: str | None = None, queue: str | None = None,
           status: str | None = None) -> list[dict]:
    """Список задач зеркала (поиск по названию/описанию, фильтры очередь/статус)."""
    with connect() as conn:
        return mirror.search_issues(conn, q, queue, status)


@router.get("/issues/{key}")
def issue_detail(key: str) -> dict:
    """Карточка задачи: описание, комментарии, вложения, история."""
    with connect() as conn:
        data = mirror.get_issue(conn, key)
    if not data:
        raise HTTPException(status_code=404, detail=f"Задачи {key} нет в зеркале")
    return data


@router.get("/attachments/{att_id}/download")
def attachment_download(att_id: int):
    """Файл вложения из локального хранилища (исходное имя, для скачивания)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, file_path FROM issue_attachments WHERE id = %s", (att_id,))
        row = cur.fetchone()
    if not row or not row["file_path"]:
        raise HTTPException(status_code=404, detail="Вложение не скачано — запустите синк")
    path = settings.attachments_dir / row["file_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл вложения отсутствует на диске")
    return FileResponse(path, filename=row["name"], media_type=guess_type(row["name"])[0])


@router.get("/mirror/status")
def mirror_status() -> dict:
    """Состояние зеркала и последней синхронизации."""
    with connect() as conn:
        return mirror.mirror_status(conn)
