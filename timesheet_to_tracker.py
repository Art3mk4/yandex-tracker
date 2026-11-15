#!/usr/bin/env python3
"""Перенос записей из TIMESHEET.md в ворклоги Яндекс Трекера.

Два пути синхронизации (дедуп одинаковый: свой ворклог за тот же день с той же
длительностью — пропустить, с другой — обновить, нет — создать):

1. sync.js (путь по умолчанию): скрипт читает таблицу «Записи» и генерирует
   timesheet.json (машиночитаемые записи, формат Chrome extension) и sync.js
   (sync-core.js + данные). sync.js выполняют во вкладке https://tracker.yandex.net
   (консоль DevTools или Claude через браузер): запросы идут к API через адрес
   веб-интерфейса /api/public/v3 с сессией браузера. Токен не нужен, куки из
   браузера не извлекаются.

2. --rest: запросы напрямую к https://api.tracker.yandex.net/v3 с OAuth-токеном
   (файл TRACKER_TOKEN_HOST_FILE из .env, по умолчанию ~/.config/yandex-tracker/token)
   и заголовком X-Org-Id. Ни браузера, ни MCP не требует; sync.js/timesheet.json
   при этом не перегенерируются.

Без --apply оба пути ничего не меняют (dry-run). Строки без ID задачи (встречи)
и с «не в Трекере» в «Источнике» не переносятся.

Примеры:
  python3 timesheet_to_tracker.py --parse-only                   # только разбор
  python3 timesheet_to_tracker.py                                # dry-run по всем записям
  python3 timesheet_to_tracker.py --task KEY-123          # JS в режиме dry-run
  python3 timesheet_to_tracker.py --task KEY-123 --apply  # JS, который записывает
  python3 timesheet_to_tracker.py --rest                   # dry-run через REST
  python3 timesheet_to_tracker.py --rest --task KEY-123 --apply  # запись через REST
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TIMESHEET = ROOT / "TIMESHEET.md"
SYNC_CORE = ROOT / "sync-core.js"
OUT_JS = ROOT / "sync.js"
OUT_JSON = ROOT / "timesheet.json"
ENV_FILE = ROOT / ".env"
# REST API Трекера (режим --rest); браузерный sync.js ходит через /api/public/v3
TRACKER_API = "https://api.tracker.yandex.net/v3"
# где лежит OAuth-токен, если TRACKER_TOKEN_HOST_FILE нигде не задан
TOKEN_FALLBACK = Path.home() / ".config" / "yandex-tracker" / "token"
TASK_RE = re.compile(r"^[A-Z]+-\d+$")
START_TIME = "18:00"  # время начала ворклога в день работы (локальная зона)


def load_env_file(path: Path) -> dict:
    """KEY=VALUE из .env проекта; {} если файла нет. Значения наружу не печатать."""
    if not path.exists():
        return {}
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("\"'")
    return env


ENV = load_env_file(ENV_FILE)
# организация Яндекс 360 (X-Org-ID), нужна только для OAuth-варианта
ORG_ID = os.environ.get("TRACKER_ORG_ID") or ENV.get("TRACKER_ORG_ID", "")

# sync.js = sync-core.js (общая логика, её же использует extension) + вызов с данными.
# Всё обёрнуто в async-функцию: повторная вставка в консоль не конфликтует по именам.
JS_WRAPPER = """// Сгенерировано timesheet_to_tracker.py {generated}. Выполнять на https://tracker.yandex.net
await (async () => {{
{core}
  const ENTRIES = {entries};
  const summary = formatSyncResult(await syncWorklogs(ENTRIES, {{apply: {apply}}}));
  console.log(summary.split(' | ').join('\\n'));
  return summary;
}})()
"""


def parse_rows(path: Path) -> list[dict]:
    """Все строки таблицы «Записи», включая строки без ID задачи и «не в Трекере».

    Каждая строка: date, task (ID или None), label (подпись строки без задачи,
    например «— (учёт времени)», иначе None), hours, comment, source.
    """
    text = path.read_text(encoding="utf-8")
    section = text.split("## Записи", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5 or not re.match(r"\d+(\.\d+)?$", cells[2]):
            continue
        day = re.search(r"\d{2}\.\d{2}\.\d{4}", cells[0])
        if not day:
            continue
        task_cell = cells[1].split()[0] if cells[1] else ""
        has_task = bool(TASK_RE.match(task_cell))
        rows.append(
            {
                "date": datetime.strptime(day.group(), "%d.%m.%Y").date(),
                "task": task_cell if has_task else None,
                "label": None if has_task else cells[1],
                "hours": float(cells[2]),
                "comment": cells[3].replace("`", ""),
                "source": cells[4],
            }
        )
    return rows


def parse_timesheet(path: Path) -> list[dict]:
    """Строки для переноса в Трекер: только с ID задачи и без «не в Трекере»."""
    return [
        {
            "date": r["date"],
            "task": r["task"],
            "hours": r["hours"],
            "comment": r["comment"],
            "source": r["source"],
        }
        for r in parse_rows(path)
        if r["task"] and "не в Трекере" not in r["source"]
    ]


def iso_duration(hours: float) -> str:
    h, m = divmod(round(hours * 60), 60)
    return "PT" + (f"{h}H" if h else "") + (f"{m}M" if m else "")


def human(hours: float) -> str:
    h, m = divmod(round(hours * 60), 60)
    return " ".join(p for p in (f"{h}ч" if h else "", f"{m}м" if m else "") if p)


def to_entries(rows: list[dict]) -> list[dict]:
    tz = datetime.now().astimezone().strftime("%z")
    return [
        {
            "task": r["task"],
            "date": f"{r['date']:%Y-%m-%d}",
            "hours": r["hours"],
            "start": f"{r['date']:%Y-%m-%d}T{START_TIME}:00.000{tz}",
            "duration": iso_duration(r["hours"]),
            "comment": r["comment"],
            "source": r["source"],
            "synced": "в Трекере" in r["source"],
        }
        for r in rows
    ]


def build_json(entries: list[dict]) -> str:
    doc = {
        "version": 1,
        "org_id": ORG_ID,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "entries": entries,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def build_js(entries: list[dict], apply: bool) -> str:
    core = SYNC_CORE.read_text(encoding="utf-8")
    items = [{k: e[k] for k in ("task", "date", "start", "duration", "comment")} for e in entries]
    return JS_WRAPPER.format(
        generated=f"{datetime.now():%d.%m.%Y %H:%M}",
        core="\n".join("  " + line if line else line for line in core.splitlines()),
        entries=json.dumps(items, ensure_ascii=False, indent=2).replace("\n", "\n  "),
        apply="true" if apply else "false",
    )


def tracker_credentials() -> tuple[str, str]:
    """OAuth-токен и org id для REST: сначала окружение, потом .env. Значения не печатать."""
    token_file = os.environ.get("TRACKER_TOKEN_HOST_FILE") or ENV.get("TRACKER_TOKEN_HOST_FILE", "")
    path = Path(token_file).expanduser() if token_file else TOKEN_FALLBACK
    if not path.exists():
        sys.exit(f"Нет файла токена ({path}) — для --rest задайте TRACKER_TOKEN_HOST_FILE в .env")
    if not ORG_ID:
        sys.exit("Нет TRACKER_ORG_ID (окружение или .env) — для --rest нужен заголовок X-Org-Id")
    return path.read_text(encoding="utf-8").strip(), ORG_ID


def duration_to_minutes(d: str) -> int:
    """Длительность ISO 8601 в минутах; Трекер считает 1 д = 8 ч, 1 н = 5 д (как sync-core.js)."""
    m = re.match(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", str(d))
    if not m:
        return 0
    w, dd, h, mm = (int(m.group(i) or 0) for i in (1, 2, 3, 4))
    return w * 2400 + dd * 480 + h * 60 + mm


def local_date(start: str) -> str:
    """Локальная дата из ISO-времени (аналог toLocaleDateString('sv-SE') в sync-core.js)."""
    dt = datetime.fromisoformat(start)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date().isoformat()


def plan_actions(
    entries: list[dict], worklogs_by_task: dict[str, list[dict]], me_display: str
) -> list[dict]:
    """Решение по каждой записи без сети — дедуп один в один как в sync-core.js.

    worklogs_by_task: {task: [ворклоги из GET /issues/<task>/worklog]}.
    Только свои ворклоги за тот же день: чужие не трогаем. Равенство — в минутах
    (сервер сворачивает 8 ч в P1D). Результат: [{task, date, to, action:
    'same' | 'update' (+from, id) | 'create'}].
    """
    results = []
    for it in entries:
        res = {"task": it["task"], "date": it["date"], "to": it["duration"]}
        mine = [
            w
            for w in worklogs_by_task.get(it["task"], [])
            if (w.get("createdBy") or {}).get("display") == me_display
            and local_date(w["start"]) == it["date"]
        ]
        if any(
            duration_to_minutes(w["duration"]) == duration_to_minutes(it["duration"])
            for w in mine
        ):
            results.append({**res, "action": "same"})
        elif mine:
            results.append({**res, "action": "update", "from": mine[0]["duration"], "id": mine[0]["id"]})
        else:
            results.append({**res, "action": "create"})
    return results


def rest_api(path: str, token: str, org: str, data=None, method: str = "GET"):
    """Тонкий слой REST API Трекера: запрос с токеном, ответ — JSON (массив или объект)."""
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        TRACKER_API + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"OAuth {token}",
            "X-Org-Id": org,
            **({"Content-Type": "application/json"} if body else {}),
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def sync_rest(entries: list[dict], apply: bool) -> int:
    """Синхронизация напрямую через REST, без браузера. 0 — расхождений/ошибок нет."""
    token, org = tracker_credentials()
    try:
        me = rest_api("/myself", token, org)
    except urllib.error.URLError as e:
        sys.exit(f"Трекер не ответил на /myself ({e}) — проверьте токен и X-Org-Id")
    print(f"Пользователь {me['display']} ({'запись' if apply else 'dry-run'})")
    cache: dict[str, list | None] = {}  # ворклоги задачи; None — читать заново или ошибка
    failed = 0
    for it in entries:
        label = f"{it['task']} {it['date']}"
        if it["task"] not in cache:
            try:
                cache[it["task"]] = rest_api(f"/issues/{it['task']}/worklog?perPage=500", token, org)
            except urllib.error.URLError as e:
                cache[it["task"]] = None
                print(f"{label} ошибка (не прочитать ворклоги: {e})")
                failed += 1
        if cache[it["task"]] is None:
            continue  # без данных создавать нельзя — получился бы дубль
        [plan] = plan_actions([it], cache, me["display"])
        if plan["action"] == "same":
            print(f"{label} без изменений {it['duration']}")
        elif not apply:
            if plan["action"] == "update":
                print(f"{label} изменится {plan['from']} → {it['duration']}")
            else:
                print(f"{label} будет {it['duration']}")
        else:
            try:
                if plan["action"] == "update":
                    rest_api(f"/issues/{it['task']}/worklog/{plan['id']}", token, org,
                             {"duration": it["duration"]}, method="PATCH")
                else:
                    rest_api(f"/issues/{it['task']}/worklog", token, org,
                             {"start": it["start"], "duration": it["duration"], "comment": it["comment"]},
                             method="POST")
                print(f"{label} {'обновлено' if plan['action'] == 'update' else 'записано'} {it['duration']}")
                cache[it["task"]] = None  # список устарел
            except urllib.error.URLError:
                # ответ мог потеряться при уже состоявшейся записи: перечитать и
                # проверить ещё раз, а не повторять запрос (иначе дубль)
                try:
                    cache[it["task"]] = rest_api(f"/issues/{it['task']}/worklog?perPage=500", token, org)
                except urllib.error.URLError:
                    cache[it["task"]] = None
                if cache[it["task"]] is not None and \
                        plan_actions([it], cache, me["display"])[0]["action"] == "same":
                    print(f"{label} записано (подтверждено перечитыванием)")
                else:
                    print(f"{label} ошибка записи")
                    failed += 1
    if failed:
        print(f"Ошибок: {failed}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--task", help="только эта задача, например KEY-123")
    parser.add_argument("--apply", action="store_true", help="записывать (иначе dry-run)")
    parser.add_argument("--rest", action="store_true",
                        help="синхронизировать напрямую через REST, без браузера и sync.js")
    parser.add_argument("--parse-only", action="store_true", help="только разобрать TIMESHEET.md")
    args = parser.parse_args()

    rows = parse_timesheet(TIMESHEET)
    if args.task:
        rows = [r for r in rows if r["task"] == args.task]
    if not rows:
        sys.exit("Нет записей для переноса")

    for r in rows:
        print(f"{r['date']:%d.%m.%Y}  {r['task']:<16} {human(r['hours']):>7}  {r['comment']}")
    print(f"Записей: {len(rows)}, часов: {sum(r['hours'] for r in rows):g}")
    if args.parse_only:
        return

    entries = to_entries(rows)
    if args.rest:
        sys.exit(sync_rest(entries, args.apply))
    OUT_JSON.write_text(build_json(entries), encoding="utf-8")
    OUT_JS.write_text(build_js(entries, args.apply), encoding="utf-8")
    mode = "ЗАПИСЬ" if args.apply else "dry-run"
    print(f"\n{OUT_JSON.name} и {OUT_JS.name} ({mode}) готовы.")
    print("Выполнить: открыть https://tracker.yandex.net → DevTools (F12) → Console →")
    print("вставить содержимое файла → Enter. Или попросить Claude выполнить его в браузере.")


if __name__ == "__main__":
    main()
