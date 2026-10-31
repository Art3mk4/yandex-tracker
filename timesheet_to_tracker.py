#!/usr/bin/env python3
"""Перенос записей из TIMESHEET.md в ворклоги Яндекс Трекера через сессию браузера.

Скрипт читает таблицу «Записи» и генерирует:
  timesheet.json — записи в машиночитаемом виде (формат для Chrome extension);
  sync.js        — sync-core.js + данные. Его выполняют во вкладке https://tracker.yandex.ru
(консоль DevTools или Claude через браузер): запросы идут к API Трекера через
адрес веб-интерфейса /api/public/v3 с вашей сессией. Токен не нужен, куки
из браузера не извлекаются.

JS синхронизирует: для каждой записи читает ворклоги задачи; если у вас за
этот день ворклога нет — создаёт, есть с другой длительностью — обновляет,
совпадает — пропускает. Без --apply ничего не меняет (dry-run). Строки без ID
задачи (встречи) и с «не в Трекере» в «Источнике» не переносятся.

Примеры:
  python3 timesheet_to_tracker.py --parse-only                   # только разбор
  python3 timesheet_to_tracker.py                                # dry-run по всем записям
  python3 timesheet_to_tracker.py --task KEY-123          # JS в режиме dry-run
  python3 timesheet_to_tracker.py --task KEY-123 --apply  # JS, который записывает
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TIMESHEET = ROOT / "TIMESHEET.md"
SYNC_CORE = ROOT / "sync-core.js"
OUT_JS = ROOT / "sync.js"
OUT_JSON = ROOT / "timesheet.json"
# организация Яндекс 360 (X-Org-ID), нужна только для OAuth-варианта
ORG_ID = os.environ.get("TRACKER_ORG_ID", "")
TASK_RE = re.compile(r"^[A-Z]+-\d+$")
START_TIME = "18:00"  # время начала ворклога в день работы (локальная зона)

# sync.js = sync-core.js (общая логика, её же использует extension) + вызов с данными.
# Всё обёрнуто в async-функцию: повторная вставка в консоль не конфликтует по именам.
JS_WRAPPER = """// Сгенерировано timesheet_to_tracker.py {generated}. Выполнять на https://tracker.yandex.ru
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--task", help="только эта задача, например KEY-123")
    parser.add_argument("--apply", action="store_true", help="JS будет записывать (иначе dry-run)")
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
    OUT_JSON.write_text(build_json(entries), encoding="utf-8")
    OUT_JS.write_text(build_js(entries, args.apply), encoding="utf-8")
    mode = "ЗАПИСЬ" if args.apply else "dry-run"
    print(f"\n{OUT_JSON.name} и {OUT_JS.name} ({mode}) готовы.")
    print("Выполнить: открыть https://tracker.yandex.ru → DevTools (F12) → Console →")
    print("вставить содержимое файла → Enter. Или попросить Claude выполнить его в браузере.")


if __name__ == "__main__":
    main()
