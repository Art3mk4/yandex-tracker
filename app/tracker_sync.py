"""Синхронизация локального зеркала Яндекс Трекера.

Зеркалит задачи (карточки), комментарии, вложения (метаданные + файлы) и
историю изменений через официальный REST API. Токен — тот же OAuth-файл,
что использует MCP yandex-tracker; в образ и репозиторий не попадает.

Запуск — явной командой (без демонов и cron):

  docker compose run --rm app python -m app.tracker_sync                  # инкремент
  docker compose run --rm app python -m app.tracker_sync --full           # перечитать всё
  docker compose run --rm app python -m app.tracker_sync --issue KEY-123
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from psycopg.types.json import Jsonb

from app.config import settings
from app.db import connect

RETRY_STATUSES = {429, 500, 502, 503, 504}
BACKOFFS = [1, 2, 4, 8]
PAUSE_BETWEEN_REQUESTS = 0.1
PAUSE_BETWEEN_ISSUES = 0.4
PER_PAGE = 100
TRUNCATION_GUARD = 800  # длинный текст комментария в списке может быть обрезан


class TrackerError(RuntimeError):
    pass


def parse_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class TrackerClient:
    """REST-клиент: ретраи на 429/5xx, паузы, пагинация."""

    def __init__(self, token: str):
        self.http = httpx.Client(
            base_url=settings.tracker_base_url,
            headers={"Authorization": f"OAuth {token}", "X-Org-ID": settings.tracker_org_id},
            timeout=30.0,
            follow_redirects=True,
        )

    def request(self, method: str, path: str, **kw) -> httpx.Response:
        for attempt in range(len(BACKOFFS) + 1):
            try:
                r = self.http.request(method, path, **kw)
            except httpx.TransportError as e:
                if attempt == len(BACKOFFS):
                    raise TrackerError(f"сеть: {e}") from e
                time.sleep(BACKOFFS[attempt])
                continue
            if r.status_code in RETRY_STATUSES and attempt < len(BACKOFFS):
                delay = r.headers.get("Retry-After")
                time.sleep(float(delay) if delay and delay.isdigit() else BACKOFFS[attempt])
                continue
            if r.status_code >= 400:
                raise TrackerError(f"HTTP {r.status_code} {method} {path}: {r.text[:200]}")
            return r
        raise TrackerError(f"HTTP {method} {path}: ретраи исчерпаны")

    def get_json(self, path: str, params: dict | None = None):
        r = self.request("GET", path, params=params)
        time.sleep(PAUSE_BETWEEN_REQUESTS)
        return r.json()

    def get_paginated(self, path: str, params: dict | None = None, max_pages: int = 50) -> list[dict]:
        """Все элементы списка: Трекер листает курсором в заголовке Link rel="next"
        (параметр page у этих эндпоинтов игнорируется)."""
        items, query = [], dict(params or {})
        query.setdefault("perPage", PER_PAGE)
        for _ in range(max_pages):  # страховочный потолок
            r = self.request("GET", path, params=query)
            time.sleep(PAUSE_BETWEEN_REQUESTS)
            batch = r.json()
            items.extend(batch)
            nxt = link_next_params(r.headers.get("link", ""))
            if not batch or not nxt:
                return items
            query.update(nxt)
        return items

    def search_keys(self, query: str) -> list[str]:
        keys: list[str] = []
        params: dict = {"perPage": PER_PAGE}
        for _ in range(50):
            r = self.request("POST", "/issues/_search", params=params, json={"query": query})
            time.sleep(PAUSE_BETWEEN_REQUESTS)
            batch = r.json()
            keys += [i["key"] for i in batch]
            nxt = link_next_params(r.headers.get("link", ""))
            if not batch or not nxt:
                return keys
            params.update(nxt)
        return keys

    def download(self, url: str, dest: Path) -> None:
        r = self.request("GET", url)
        time.sleep(PAUSE_BETWEEN_REQUESTS)
        dest.write_bytes(r.content)


def sanitize(name: str) -> str:
    return name.replace("/", "_").replace("\\", "_").replace("\x00", "") or "file"


def link_next_params(link_header: str) -> dict | None:
    """Параметры следующей страницы из Link: <url>; rel="next" (курсор id и т. п.)."""
    import urllib.parse as up

    for part in link_header.split(","):
        if 'rel="next"' not in part or "<" not in part:
            continue
        url = part[part.find("<") + 1 : part.find(">")]
        query = {k: v[0] for k, v in up.parse_qs(up.urlparse(url).query).items() if v and v[0]}
        return query or None
    return None


def sync_issue(client: TrackerClient, conn, key: str, full: bool) -> dict:
    """Синк одной задачи; одна транзакция, ошибка откатывает только её."""
    card = client.get_json(f"/issues/{key}")
    issue_id = card["id"]
    cur_key = card["key"]
    stats = {"status": "", "comments_new": 0, "attachments_new": 0,
             "changelog_new": 0, "files_downloaded": 0, "bytes": 0}

    with conn.cursor() as cur:
        cur.execute("SELECT key, updated_at FROM issues WHERE id = %s", (issue_id,))
        row = cur.fetchone()

    if row and not full and row["updated_at"] == parse_ts(card.get("updatedAt")):
        return {"status": "unchanged"}

    with conn.transaction():
        with conn.cursor() as cur:
            stats["status"] = "new" if not row else "updated"

            aliases = set(card.get("aliases") or [])
            if row and row["key"] != cur_key:
                aliases.add(row["key"])  # перенос задачи между очередями

            issue_values = {
                "id": issue_id,
                "key": cur_key,
                "summary": card.get("summary") or "",
                "description": card.get("description") or "",
                "queue": (card.get("queue") or {}).get("key", ""),
                "queue_name": (card.get("queue") or {}).get("display", ""),
                "status_key": (card.get("status") or {}).get("key"),
                "status_name": (card.get("status") or {}).get("display"),
                "type_name": (card.get("type") or {}).get("display"),
                "priority_name": (card.get("priority") or {}).get("display"),
                "assignee": (card.get("assignee") or {}).get("login"),
                "assignee_name": (card.get("assignee") or {}).get("display"),
                "created_by": (card.get("createdBy") or {}).get("login"),
                "created_by_name": (card.get("createdBy") or {}).get("display"),
                "followers": Jsonb([{"login": f.get("login"), "display": f.get("display")}
                                    for f in card.get("followers") or []]),
                "tags": Jsonb(card.get("tags") or []),
                "created_at": card.get("createdAt"),
                "updated_at": card.get("updatedAt"),
                "resolved_at": card.get("resolvedAt"),
                "raw": Jsonb(card),
            }
            cur.execute(
                """INSERT INTO issues (id, key, summary, description, queue, queue_name,
                         status_key, status_name, type_name, priority_name,
                         assignee, assignee_name, created_by, created_by_name,
                         followers, tags, created_at, updated_at, resolved_at, raw, synced_at)
                   VALUES (%(id)s, %(key)s, %(summary)s, %(description)s, %(queue)s, %(queue_name)s,
                           %(status_key)s, %(status_name)s, %(type_name)s, %(priority_name)s,
                           %(assignee)s, %(assignee_name)s, %(created_by)s, %(created_by_name)s,
                           %(followers)s, %(tags)s, %(created_at)s, %(updated_at)s,
                           %(resolved_at)s, %(raw)s, now())
                   ON CONFLICT (id) DO UPDATE SET
                     key = EXCLUDED.key, summary = EXCLUDED.summary,
                     description = EXCLUDED.description, queue = EXCLUDED.queue,
                     queue_name = EXCLUDED.queue_name, status_key = EXCLUDED.status_key,
                     status_name = EXCLUDED.status_name, type_name = EXCLUDED.type_name,
                     priority_name = EXCLUDED.priority_name, assignee = EXCLUDED.assignee,
                     assignee_name = EXCLUDED.assignee_name, created_by = EXCLUDED.created_by,
                     created_by_name = EXCLUDED.created_by_name, followers = EXCLUDED.followers,
                     tags = EXCLUDED.tags, created_at = EXCLUDED.created_at,
                     updated_at = EXCLUDED.updated_at, resolved_at = EXCLUDED.resolved_at,
                     raw = EXCLUDED.raw, synced_at = now()""",
                issue_values,
            )
            for alias in aliases - {cur_key}:
                cur.execute(
                    """INSERT INTO issue_aliases (alias, issue_id) VALUES (%s, %s)
                       ON CONFLICT (alias) DO UPDATE SET issue_id = EXCLUDED.issue_id, seen_at = now()""",
                    (alias, issue_id),
                )

            # --- комментарии ---
            comments = client.get_paginated(f"/issues/{key}/comments")
            for c in comments:
                if c.get("text") and len(c["text"]) >= TRUNCATION_GUARD:
                    try:  # страховка обрезки: дотянуть полный текст поштучно
                        detail = client.get_json(f"/issues/{cur_key}/comments/{c['id']}")
                        c["text"] = detail.get("text") or c["text"]
                    except TrackerError:
                        pass
            cur.execute("SELECT id FROM issue_comments WHERE issue_id = %s", (issue_id,))
            existing = {r["id"] for r in cur.fetchall()}
            for c in comments:
                cur.execute(
                    """INSERT INTO issue_comments (id, issue_id, long_id, text, author, author_name,
                                 created_at, updated_at, version, transport, type, raw, synced_at)
                       VALUES (%(id)s, %(issue_id)s, %(long_id)s, %(text)s, %(author)s, %(author_name)s,
                               %(created_at)s, %(updated_at)s, %(version)s, %(transport)s, %(type)s,
                               %(raw)s, now())
                       ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text,
                         author = EXCLUDED.author, author_name = EXCLUDED.author_name,
                         updated_at = EXCLUDED.updated_at, version = EXCLUDED.version,
                         raw = EXCLUDED.raw, synced_at = now()""",
                    {
                        "id": c["id"], "issue_id": issue_id, "long_id": c.get("longId"),
                        "text": c.get("text") or "", "author": (c.get("createdBy") or {}).get("login"),
                        "author_name": (c.get("createdBy") or {}).get("display"),
                        "created_at": c.get("createdAt"), "updated_at": c.get("updatedAt"),
                        "version": c.get("version"), "transport": c.get("transport"),
                        "type": c.get("type"), "raw": Jsonb(c),
                    },
                )
            stats["comments_new"] = len({c["id"] for c in comments} - existing)
            if comments:
                cur.execute(
                    "DELETE FROM issue_comments WHERE issue_id = %s AND id <> ALL(%s)",
                    (issue_id, [c["id"] for c in comments]),
                )

            # --- вложения: метаданные + скачивание ---
            atts = client.get_paginated(f"/issues/{key}/attachments")
            cur.execute("SELECT id FROM issue_attachments WHERE issue_id = %s", (issue_id,))
            existing_att = {r["id"] for r in cur.fetchall()}
            for a in atts:
                rel_path = f"{cur_key}/{a['id']}_{sanitize(a.get('name') or '')}"
                cur.execute(
                    """INSERT INTO issue_attachments (id, issue_id, name, size, mimetype, author,
                                 created_at, content_url, raw, synced_at)
                       VALUES (%(id)s, %(issue_id)s, %(name)s, %(size)s, %(mimetype)s, %(author)s,
                               %(created_at)s, %(content_url)s, %(raw)s, now())
                       ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, size = EXCLUDED.size,
                         mimetype = EXCLUDED.mimetype, content_url = EXCLUDED.content_url,
                         raw = EXCLUDED.raw, synced_at = now()""",
                    {
                        "id": int(a["id"]), "issue_id": issue_id, "name": a.get("name") or "",
                        "size": a.get("size") or 0, "mimetype": a.get("mimetype"),
                        "author": (a.get("createdBy") or {}).get("login"),
                        "created_at": a.get("createdAt"), "content_url": a.get("content") or "",
                        "raw": Jsonb(a),
                    },
                )
                dest = settings.attachments_dir / rel_path
                if a.get("content") and not (
                    dest.exists() and dest.stat().st_size == (a.get("size") or 0)
                ):
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    client.download(a["content"], dest)
                    stats["files_downloaded"] += 1
                    stats["bytes"] += a.get("size") or 0
                cur.execute(
                    "UPDATE issue_attachments SET file_path = %s, downloaded_at = now() WHERE id = %s",
                    (rel_path, int(a["id"])),
                )
            stats["attachments_new"] = len({int(a["id"]) for a in atts} - existing_att)
            if atts:
                cur.execute(
                    "DELETE FROM issue_attachments WHERE issue_id = %s AND id <> ALL(%s)",
                    (issue_id, [int(a["id"]) for a in atts]),
                )

            # --- changelog ---
            changes = client.get_paginated(f"/issues/{key}/changelog")
            cur.execute("SELECT id FROM issue_changelog WHERE issue_id = %s", (issue_id,))
            existing_cl = {r["id"] for r in cur.fetchall()}
            for ch in changes:
                cur.execute(
                    """INSERT INTO issue_changelog (id, issue_id, updated_at, author, author_name,
                                 transport, type, fields, raw, synced_at)
                       VALUES (%(id)s, %(issue_id)s, %(updated_at)s, %(author)s, %(author_name)s,
                               %(transport)s, %(type)s, %(fields)s, %(raw)s, now())
                       ON CONFLICT (id) DO UPDATE SET updated_at = EXCLUDED.updated_at,
                         fields = EXCLUDED.fields, raw = EXCLUDED.raw, synced_at = now()""",
                    {
                        "id": ch["id"], "issue_id": issue_id, "updated_at": ch.get("updatedAt"),
                        "author": (ch.get("updatedBy") or {}).get("login"),
                        "author_name": (ch.get("updatedBy") or {}).get("display"),
                        "transport": ch.get("transport"), "type": ch.get("type"),
                        "fields": Jsonb(ch.get("fields") or []), "raw": Jsonb(ch),
                    },
                )
            stats["changelog_new"] = len({c["id"] for c in changes} - existing_cl)
            if changes:
                cur.execute(
                    "DELETE FROM issue_changelog WHERE issue_id = %s AND id <> ALL(%s)",
                    (issue_id, [c["id"] for c in changes]),
                )

    return stats


def collect_keys(conn, client: TrackerClient) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT task_key FROM time_entries WHERE task_key IS NOT NULL")
        keys = [r["task_key"] for r in cur.fetchall()]
        cur.execute("SELECT key FROM issues")
        keys += [r["key"] for r in cur.fetchall()]
        cur.execute("SELECT alias FROM issue_aliases")
        keys += [r["alias"] for r in cur.fetchall()]
    login = client.get_json("/myself")["login"]
    keys += client.search_keys(f"assignee: {login} OR author: {login}")
    seen, ordered = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            ordered.append(k)
    return ordered


def update_sync_state(conn, mode: str, duration: float, stats: dict, errors: list) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM issues", ())
        total = cur.fetchone()["n"]
        cur.execute(
            """UPDATE sync_state SET last_run_at = now(), last_mode = %s, last_duration_sec = %s,
                 issues_total = %s, stats = %s, errors = %s, updated_at = now() WHERE id = 1""",
            (mode, round(duration, 1), total, Jsonb(stats), Jsonb(errors)),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Синхронизация зеркала Яндекс Трекера")
    parser.add_argument("--full", action="store_true", help="перечитать задачи целиком")
    parser.add_argument("--issue", action="append", metavar="KEY", help="синхронизировать задачу")
    args = parser.parse_args()

    token_file = settings.tracker_token_file
    if not token_file.exists() or not token_file.read_text(encoding="utf-8").strip():
        sys.exit(f"нет OAuth-токена в {token_file} — синк недоступен "
                 f"(переменная TRACKER_TOKEN_HOST_FILE в .env)")

    client = TrackerClient(token_file.read_text(encoding="utf-8").strip())
    mode = "issue" if args.issue else ("full" if args.full else "incremental")
    started = time.monotonic()
    totals = {"new": 0, "updated": 0, "unchanged": 0}
    sum_stats = {"comments_new": 0, "attachments_new": 0, "changelog_new": 0,
                 "files_downloaded": 0, "bytes": 0}
    errors = []

    with connect() as conn:
        keys = args.issue or collect_keys(conn, client)
        print(f"синк ({mode}): задач в наборе {len(keys)}")
        for i, key in enumerate(keys, 1):
            try:
                result = sync_issue(client, conn, key, args.full)
                if result["status"] == "unchanged":
                    totals["unchanged"] += 1
                else:
                    totals[result["status"]] += 1
                    for k in sum_stats:
                        sum_stats[k] += result.get(k, 0)
                print(f"[{i}/{len(keys)}] {key}: {result['status']}"
                      + (f", коммент. +{result['comments_new']}, "
                         f"вложений +{result['attachments_new']} "
                         f"(скачано {result['files_downloaded']}), "
                         f"changelog +{result['changelog_new']}"
                         if result["status"] != "unchanged" else ""))
            except TrackerError as e:
                errors.append({"key": key, "error": str(e)})
                print(f"[{i}/{len(keys)}] {key}: ОШИБКА {e}", file=sys.stderr)
            time.sleep(PAUSE_BETWEEN_ISSUES)

        duration = time.monotonic() - started
        report = {**{f"issues_{k}": v for k, v in totals.items()}, **sum_stats}
        update_sync_state(conn, mode, duration, report, errors)

    mins, secs = divmod(int(duration), 60)
    print(f"итог: задач новых {totals['new']}, обновлено {totals['updated']}, "
          f"без изменений {totals['unchanged']}; комментариев +{sum_stats['comments_new']}, "
          f"вложений +{sum_stats['attachments_new']} "
          f"(скачано {sum_stats['files_downloaded']} шт., {sum_stats['bytes'] / 1e6:.1f} МБ), "
          f"changelog +{sum_stats['changelog_new']}; ошибок {len(errors)}; {mins} мин {secs} с")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
