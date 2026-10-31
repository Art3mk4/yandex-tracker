"""Импорт TIMESHEET.md в Postgres — идемпотентный upsert.

Читает все строки «Записей» через parse_rows() из timesheet_to_tracker.py
(в контейнере файл примонтирован рядом). Источник истины остаётся TIMESHEET.md:
повторный импорт ничего не меняет, удалённые из табеля записи не удаляются.

Примеры:
  python -m app.import_timesheet --dry-run   # что изменилось бы
  python -m app.import_timesheet             # импорт
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.config import settings
from app.db import connect

# Проекты — локальный projects.json (не публикуется):
# [{"code": "my-project", "sessions_path": "~/.claude/projects/...", "since": "2026-09-24"}]
PROJECTS_FILE = Path("projects.json")


def load_projects() -> list[tuple[str, str, date]]:
    example = (
        f"нет {PROJECTS_FILE} — создайте список проектов (локальный файл, не в git):\n"
        f'[{{"code": "my-project", "sessions_path": "~/.claude/projects/…", '
        f'"since": "2026-09-24"}}]'
    )
    try:
        text = PROJECTS_FILE.read_text(encoding="utf-8")
    except OSError:
        sys.exit(example)
    if not text.strip():
        sys.exit(example)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        sys.exit(f"{PROJECTS_FILE} не читается как JSON.\n{example}")
    return [(p["code"], p["sessions_path"], date.fromisoformat(p["since"])) for p in raw]


IN_TRACKER_RE = re.compile(r",\s*(не )?в Трекере$")

UPSERT_SQL = """
INSERT INTO time_entries
    (work_date, task_key, label, hours, description, estimate_source, tracker_state, project_id)
VALUES
    (%(work_date)s, %(task_key)s, %(label)s, %(hours)s, %(description)s,
     %(estimate_source)s, %(tracker_state)s,
     (SELECT id FROM projects p WHERE p.since <= %(work_date)s ORDER BY p.since DESC LIMIT 1))
ON CONFLICT (work_date, COALESCE(task_key, label)) DO UPDATE SET
    hours = EXCLUDED.hours,
    description = EXCLUDED.description,
    estimate_source = EXCLUDED.estimate_source,
    tracker_state = EXCLUDED.tracker_state,
    project_id = EXCLUDED.project_id,
    updated_at = now()
WHERE (time_entries.hours, time_entries.description, time_entries.estimate_source,
       time_entries.tracker_state, time_entries.project_id)
    IS DISTINCT FROM
      (EXCLUDED.hours, EXCLUDED.description, EXCLUDED.estimate_source,
       EXCLUDED.tracker_state, EXCLUDED.project_id)
RETURNING (xmax = 0) AS inserted
"""


@dataclass
class ImportResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    total_hours: float = 0.0

    @property
    def total_rows(self) -> int:
        return self.inserted + self.updated + self.unchanged


def tracker_state(source: str) -> str:
    """«не в Трекере» проверять первым: подстрока «в Трекере» входит в неё."""
    if "не в Трекере" in source:
        return "excluded"
    if "в Трекере" in source:
        return "synced"
    return "pending"


def sync_log_text(path: Path) -> str | None:
    """Строка «- История синхронизации: …» из шапки табеля."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- История синхронизации:"):
            return line[len("- История синхронизации:"):].strip()
    return None


def load_rows(path: Path) -> list[dict]:
    from timesheet_to_tracker import parse_rows  # монтируется/лежит рядом

    return [
        {
            "work_date": r["date"],
            "task_key": r["task"],
            "label": r["label"],
            "hours": Decimal(str(r["hours"])),
            "description": r["comment"],
            "estimate_source": IN_TRACKER_RE.sub("", r["source"]),
            "tracker_state": tracker_state(r["source"]),
        }
        for r in parse_rows(path)
    ]


def run_import(dry_run: bool = False, path: Path | None = None) -> ImportResult:
    """Импорт табеля; при dry_run ничего не пишет."""
    path = path or settings.timesheet_path
    rows = load_rows(path)
    result = ImportResult(total_hours=float(sum(r["hours"] for r in rows)))

    with connect() as conn:
        _ensure_projects(conn)

        if dry_run:
            existing = _existing_keys(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT id, since FROM projects ORDER BY since")
                since_rows = cur.fetchall()
            for r in rows:
                key = (r["work_date"], r["task_key"] or r["label"])
                cur_row = existing.get(key)
                expected_project = next(
                    (p["id"] for p in reversed(since_rows) if p["since"] <= r["work_date"]), None)
                if cur_row is None:
                    result.inserted += 1
                elif _row_changed(cur_row, r, expected_project):
                    result.updated += 1
                    print(f"изменится {r['work_date']:%d.%m.%Y} "
                          f"{r['task_key'] or r['label']}: {cur_row['hours']} → {r['hours']}")
                else:
                    result.unchanged += 1
            return result

        with conn.cursor() as cur:
            for r in rows:
                cur.execute(UPSERT_SQL, r)
                inserted = cur.fetchone()  # None — сработал WHERE (без изменений)
                if inserted is None:
                    result.unchanged += 1
                elif inserted["inserted"]:
                    result.inserted += 1
                else:
                    result.updated += 1

        log_text = sync_log_text(path)
        if log_text is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sync_log (id, text) VALUES (1, %(text)s)
                       ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text, recorded_at = now()
                       WHERE sync_log.text IS DISTINCT FROM EXCLUDED.text""",
                    {"text": log_text},
                )
    return result


def _ensure_projects(conn) -> None:
    for code, sessions_path, since in load_projects():
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO projects (code, sessions_path, since) VALUES (%s, %s, %s)
                   ON CONFLICT (code) DO UPDATE
                   SET sessions_path = EXCLUDED.sessions_path, since = EXCLUDED.since""",
                (code, sessions_path, since),
            )


def _existing_keys(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT work_date, COALESCE(task_key, label) AS key, hours,
                              description, estimate_source, tracker_state, project_id
                       FROM time_entries""")
        return {(row["work_date"], row["key"]): row for row in cur.fetchall()}


def _row_changed(existing: dict, new: dict, expected_project: int | None) -> bool:
    return (
        existing["hours"] != new["hours"]
        or existing["description"] != new["description"]
        or existing["estimate_source"] != new["estimate_source"]
        or existing["tracker_state"] != new["tracker_state"]
        or existing["project_id"] != expected_project
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт TIMESHEET.md в Postgres")
    parser.add_argument("--dry-run", action="store_true", help="показать изменения, не записывая")
    parser.add_argument("--file", type=Path, help="путь к TIMESHEET.md (по умолчанию из конфига)")
    args = parser.parse_args()

    result = run_import(dry_run=args.dry_run, path=args.file)
    verb = "будет" if args.dry_run else "импорт"
    print(f"{verb}: новых {result.inserted}, изменённых {result.updated}, "
          f"без изменений {result.unchanged}; всего часов {result.total_hours:g}")
    if not args.dry_run and result.updated == 0 and result.inserted == 0:
        print("повторный запуск ничего не изменил (идемпотентность)")


if __name__ == "__main__":
    sys.exit(main())
