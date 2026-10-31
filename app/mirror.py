"""SQL-слой зеркала Трекера — общий для API и MCP."""
from app.config import settings


def search_issues(conn, q: str | None = None, queue: str | None = None,
                  status: str | None = None) -> list[dict]:
    """Список задач зеркала с итогами (комментарии, вложения, часы табеля)."""
    where, params = [], {}
    if q:
        where.append("(i.summary ILIKE '%%' || %(q)s || '%%' OR i.description ILIKE '%%' || %(q)s || '%%')")
        params["q"] = q
    if queue:
        where.append("i.queue = %(queue)s")
        params["queue"] = queue
    if status:
        where.append("i.status_key = %(status)s")
        params["status"] = status
    cond = ("WHERE " + " AND ".join(where)) if where else ""

    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT i.key, i.summary, i.queue, i.status_key, i.status_name,
                       i.assignee_name, i.updated_at::text AS updated_at,
                       (SELECT count(*) FROM issue_comments c WHERE c.issue_id = i.id) AS comments_count,
                       (SELECT count(*) FROM issue_attachments a WHERE a.issue_id = i.id) AS attachments_count,
                       (SELECT sum(te.hours)::float8 FROM time_entries te
                          WHERE te.task_key = i.key
                             OR te.task_key IN (SELECT alias FROM issue_aliases al WHERE al.issue_id = i.id)
                       ) AS timesheet_hours
                FROM issues i
                {cond}
                ORDER BY i.updated_at DESC NULLS LAST""",
            params,
        )
        return cur.fetchall()


def get_issue(conn, key: str) -> dict | None:
    """Карточка задачи по ключу ИЛИ алиасу, с комментариями, вложениями, историей."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT i.* FROM issues i
               WHERE i.key = %(key)s
                  OR EXISTS (SELECT 1 FROM issue_aliases a
                             WHERE a.alias = %(key)s AND a.issue_id = i.id)""",
            {"key": key},
        )
        issue = cur.fetchone()
        if not issue:
            return None
        cur.execute(
            """SELECT id, author_name, text, created_at, updated_at
               FROM issue_comments WHERE issue_id = %s ORDER BY created_at""",
            (issue["id"],),
        )
        comments = cur.fetchall()
        cur.execute(
            """SELECT id, name, size, file_path, downloaded_at,
                      CASE WHEN file_path IS NOT NULL
                           THEN '/api/attachments/' || id || '/download' END AS url
               FROM issue_attachments WHERE issue_id = %s ORDER BY id""",
            (issue["id"],),
        )
        attachments = cur.fetchall()
        cur.execute(
            """SELECT updated_at, author_name, fields
               FROM issue_changelog WHERE issue_id = %s ORDER BY updated_at""",
            (issue["id"],),
        )
        changelog = [
            {"updated_at": r["updated_at"], "author_name": r["author_name"],
             "changes": normalize_changelog(r["fields"])}
            for r in cur.fetchall()
        ]
        cur.execute("SELECT alias FROM issue_aliases WHERE issue_id = %s", (issue["id"],))
        aliases = [r["alias"] for r in cur.fetchall()]
    issue = dict(issue)
    issue.pop("raw", None)
    issue["aliases"] = aliases
    return {"issue": issue, "comments": comments, "attachments": attachments,
            "changelog": changelog}


def normalize_changelog(fields) -> list[dict]:
    """fields Трекера → [{field, from, to}] человекочитаемо."""
    out = []
    for f in fields or []:
        if not isinstance(f, dict):
            continue
        out.append({
            "field": f.get("field") or f.get("name") or "",
            "from": _chvalue(f.get("from")),
            "to": _chvalue(f.get("to")),
        })
    return out


def _chvalue(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        return v.get("display") or v.get("name") or v.get("key") or str(v)
    if isinstance(v, list):
        return ", ".join(_chvalue(x) for x in v)
    return str(v)


def mirror_status(conn) -> dict:
    """Состояние зеркала; мягкая деградация, если пусто/нет токена.

    Токен проверяем через stat(), не читая: приложение работает под appuser
    и прав на чтение 0600-файла не имеет (синк запускается под uid хоста).
    """
    try:
        token_configured = settings.tracker_token_file.stat().st_size > 0
    except OSError:
        token_configured = False
    state = {"configured": token_configured}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('issues') AS t")
            if cur.fetchone()["t"] is None:
                return state
            cur.execute("SELECT * FROM sync_state WHERE id = 1")
            row = cur.fetchone()
            if row:
                state.update({
                    "last_run_at": row["last_run_at"],
                    "last_mode": row["last_mode"],
                    "last_duration_sec": row["last_duration_sec"],
                    "issues_total": row["issues_total"],
                    "stats": row["stats"],
                    "errors": row["errors"],
                })
            cur.execute(
                """SELECT (SELECT count(*) FROM issues) AS issues,
                          (SELECT count(*) FROM issue_comments) AS comments,
                          (SELECT count(*) FROM issue_attachments) AS attachments,
                          (SELECT coalesce(sum(size), 0) FROM issue_attachments
                           WHERE downloaded_at IS NOT NULL) AS bytes"""
            )
            state.update(cur.fetchone())
    except Exception:
        pass  # зеркало опционально — дашборд работает и без него
    return state
