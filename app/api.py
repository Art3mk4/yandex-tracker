"""JSON API дашборда: записи, итоги, проекты + зеркало Трекера. Префикс /api.

Все списочные эндпоинты табеля принимают один и тот же набор фильтров
(entry_filters), поэтому плитки, графики и таблица всегда показывают
один срез данных.
"""
from datetime import date
from mimetypes import guess_type

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app import mirror
from app.config import settings
from app.db import connect

router = APIRouter(prefix="/api")


def entry_filters(
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: int | None = None,
    queue: str | None = None,
    task: str | None = None,
    state: str | None = None,
) -> tuple[str, dict]:
    """Общий WHERE для time_entries (пустая строка — без фильтров)."""
    where, params = [], {}
    if date_from:
        where.append("work_date >= %(date_from)s")
        params["date_from"] = date_from
    if date_to:
        where.append("work_date <= %(date_to)s")
        params["date_to"] = date_to
    if project_id:
        where.append("project_id = %(project_id)s")
        params["project_id"] = project_id
    if queue:
        where.append("split_part(task_key, '-', 1) = %(queue)s")
        params["queue"] = queue
    if task:
        # в psycopg литеральный % экранируется как %%
        where.append(
            "(task_key ILIKE '%%' || %(task)s || '%%' OR label ILIKE '%%' || %(task)s || '%%')"
        )
        params["task"] = task
    if state:
        where.append("tracker_state = %(state)s")
        params["state"] = state
    return (" WHERE " + " AND ".join(where)) if where else "", params


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
def entries(
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: int | None = None,
    queue: str | None = None,
    task: str | None = None,
    state: str | None = None,
) -> dict:
    where, params = entry_filters(date_from, date_to, project_id, queue, task, state)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT e.id, e.work_date, e.task_key, e.label, e.hours::float8 AS hours,
                       e.description, e.estimate_source, e.tracker_state,
                       jsonb_build_object('id', p.id, 'code', p.code) AS project
                FROM time_entries e LEFT JOIN projects p ON p.id = e.project_id
                {where}
                ORDER BY e.work_date DESC, e.id DESC""",
            params,
        )
        rows = cur.fetchall()
    return {
        "entries": rows,
        "count": len(rows),
        "total_hours": round(sum(r["hours"] for r in rows), 2) if rows else 0,
    }


@router.get("/totals/daily")
def totals_daily(
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: int | None = None,
    queue: str | None = None,
    task: str | None = None,
    state: str | None = None,
) -> dict:
    where, params = entry_filters(date_from, date_to, project_id, queue, task, state)
    sql = (
        "SELECT work_date, hours::float8 AS hours, entries FROM v_daily_totals ORDER BY work_date"
        if not where
        else f"""SELECT work_date, sum(hours)::float8 AS hours, count(*) AS entries
                 FROM time_entries{where} GROUP BY work_date ORDER BY work_date"""
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        days = cur.fetchall()
    return {"days": days, "total_hours": round(sum(d["hours"] for d in days), 2) if days else 0}


@router.get("/totals/tasks")
def totals_tasks(
    top: int = Query(15, ge=1, le=50),
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: int | None = None,
    queue: str | None = None,
    task: str | None = None,
    state: str | None = None,
) -> dict:
    where, params = entry_filters(date_from, date_to, project_id, queue, task, state)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT COALESCE(task_key, label) AS task,
                       split_part(task_key, '-', 1) AS queue,
                       sum(hours)::float8 AS hours, count(*) AS entries
                FROM time_entries{where}
                GROUP BY 1, 2
                ORDER BY hours DESC, task""",
            params,
        )
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
