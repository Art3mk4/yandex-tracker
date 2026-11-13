#!/usr/bin/env python3
"""Оценка часов по дням и задачам из локальных источников — черновик для TIMESHEET.md.

Источники:
  сессии             ~/.claude, ~/.claude-zai, ~/.claude-local (/projects/*/**.jsonl) —
                     Claude Code, GLM по API и локальная модель; все проекты, включая
                     агентов (<сессия>/subagents/); задача — ID, упомянутый последним
                     в тексте пользователя или ассистента (сводки компакций, вложения и
                     результаты инструментов не считаются);
  вне чата            паузы 20–180 мин, когда ассистент попросил действие (выполнить
                      в консоли, Portainer, деплой) или пользователь вернулся с
                      вставленным выводом — выкатка, SQL на стенде и т. п.;
  ресурс модели       выходные токены главной сессии и агентов / --tokens-per-hour;
                      коэффициент подбирает --calibrate по согласованным дням табеля;
  git reflog          окна, пока выгружена ветка задачи (management-147 → MANAGEMENT-147);
  --extra FILE        JSON с дополнительными оценками (GitLab, почта, вручную, extension):
                      {"tasks": [{"date": "YYYY-MM-DD", "task": "KEY-1", "hours": 1.5, "source": "…"}]}

Правила: активность — промежутки ≤ 20 мин; параллельные сессии не
удваиваются (время делится между задачами); для пары «день — задача» берётся максимум
по источникам, итог дня — среднее времени и ресурса, но не меньше
времени и не больше окна работы (сегодня — не раньше загрузки машины); полный день не меньше --full-day (8 ч), длиннее --max-day — предупреждение
(--cap — урезать); шаг 0,25 ч, метод наибольшего остатка; текущий день — как есть.
Время без ID задачи — строка «(проект)», её привязать вручную.

Примеры:
  python3 estimate.py --from 2026-10-26 --to 2026-10-26
  python3 estimate.py --from 2026-10-19 --to 2026-10-23 --calibrate TIMESHEET.md
  python3 estimate.py --from 2026-09-24 --to 2026-09-29 --sessions ~/.claude/projects/<папка> --json
"""
import argparse
import json
import re
import statistics
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

GAP = timedelta(minutes=20)  # промежуток больше — перерыв, не работа
OUTSIDE_MAX = timedelta(hours=3)  # дольше — перерыв даже при работе вне чата
STEP = 0.25
DEFAULT_PREFIXES = "MANAGEMENT,BACKEND,ANALYTICS,TESTING,FRONTEND,MOBILE"
TOKENS_PER_HOUR = 150_000  # выходных токенов на час работы; уточняется --calibrate
# Корни сессий: Claude Code, замена на GLM по API и локальная модель —
# схема журналов совместима, лишние типы строк парсер игнорирует
SESSION_ROOTS = [Path.home() / harness / "projects"
                 for harness in (".claude", ".claude-zai", ".claude-local")]
CODE_ROOT = Path(__file__).resolve().parent.parent
ASKS_ACTION = re.compile(
    r"выполните|запустите|нажмите|вставьте|пришлите|в консол|portainer|deploy|деплой|"
    r"pipeline|run pipeline|! ", re.IGNORECASE)


@dataclass
class Event:
    when: datetime
    kind: str  # human | assistant | tool | compact
    text: str = ""
    tokens: int = 0
    pasted: bool = False


def thousands(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def task_re(prefixes: list[str]) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(prefixes) + r")[-_ ](\d+)\b", re.IGNORECASE)


def project_name(folder: Path) -> str:
    """-home-user-development-my-app → my-app (путь сессий через дефисы)."""
    slug = str(CODE_ROOT).replace("/", "-").replace("_", "-") + "-"
    return folder.name[len(slug):] if folder.name.startswith(slug) else folder.name


def text_parts(content) -> tuple[str, bool]:
    """Текст сообщения без результатов инструментов; второй элемент — есть ли tool_result."""
    if isinstance(content, str):
        return content, False
    parts, tool = [], False
    for c in content or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "tool_result":
            tool = True
        elif c.get("type") == "text":
            parts.append(c.get("text") or "")
    return " ".join(parts), tool


def read_events(path: Path) -> list[Event]:
    events = []
    for line in path.open(encoding="utf-8", errors="ignore"):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts, kind = obj.get("timestamp"), obj.get("type")
        if not ts:
            continue
        when = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        message = obj.get("message") or {}
        if obj.get("subtype") == "compact_boundary":
            events.append(Event(when, "compact", "boundary"))
        elif obj.get("isCompactSummary"):
            events.append(Event(when, "compact", "summary"))
        elif kind == "assistant":
            text, _ = text_parts(message.get("content"))
            tokens = (message.get("usage") or {}).get("output_tokens") or 0
            events.append(Event(when, "assistant", text, tokens))
        elif kind == "user" and not obj.get("isMeta"):
            text, tool = text_parts(message.get("content"))
            if tool and not text:
                events.append(Event(when, "tool"))
            else:
                events.append(Event(when, "human", text, pasted="<pasted_content" in text))
    events.sort(key=lambda e: e.when)
    return events


class Sessions:
    """Интервалы работы, ресурс и компакции по сессиям Claude Code."""

    def __init__(self, folders: list[Path], rx: re.Pattern):
        self.rx = rx
        self.intervals = []  # (начало, конец, задача, источник)
        self.tokens = defaultdict(int)  # (день, задача) → выходные токены
        self.day = defaultdict(lambda: {"compactions": 0, "agents": 0, "tokens": 0,
                                        "first": None, "last": None})
        self.last = defaultdict(dict)  # папка → {день: последнее событие}
        for folder in folders:
            for f in sorted(folder.glob("*.jsonl")):
                timeline = self.add_session(f, f"({project_name(folder)})", self.last[folder.name])
                for agent in sorted((folder / f.stem / "subagents").glob("*.jsonl")):
                    self.add_agent(agent, timeline)

    def task_of(self, text: str):
        ids = [f"{a.upper()}-{b}" for a, b in self.rx.findall(text)]
        # самый частый; при равенстве — упомянутый последним (не порядок set)
        return max(reversed(ids), key=ids.count) if ids else None

    def add_session(self, path: Path, fallback: str, last: dict) -> list:
        timeline, current, prev, last_said = [], fallback, None, ""
        marks = defaultdict(lambda: defaultdict(int))  # день → вид отметки → число
        for e in read_events(path):
            last[e.when.date()] = max(last.get(e.when.date(), e.when), e.when)
            stats = self.day[e.when.date()]
            stats["first"] = min(filter(None, [stats["first"], e.when]))
            stats["last"] = max(filter(None, [stats["last"], e.when]))
            if e.kind == "compact":
                marks[e.when.date()][e.text] += 1
            if e.kind in ("human", "assistant"):
                current = self.task_of(e.text) or current
                timeline.append((e.when, current))
            if e.kind == "assistant":
                stats["tokens"] += e.tokens
                self.tokens[(e.when.date(), current)] += e.tokens
                if e.text:
                    last_said = e.text
            if prev:
                gap = e.when - prev
                if gap <= GAP:
                    self.intervals.append((prev, e.when, current, "сессии"))
                elif gap <= OUTSIDE_MAX and e.kind == "human" and (
                        e.pasted or ASKS_ACTION.search(last_said[-600:])):
                    self.intervals.append((prev, e.when, current, "вне чата"))
                elif e.kind in ("tool", "compact"):
                    # долгий инструмент или компакция: не больше обычной паузы
                    self.intervals.append((prev, prev + GAP, current, "сессии"))
            prev = e.when
        # у компакции две записи (граница и сводка) — считать одну
        for day, kinds in marks.items():
            self.day[day]["compactions"] += max(kinds.values())
        return timeline

    def add_agent(self, path: Path, timeline: list) -> None:
        events = read_events(path)
        if not events:
            return
        start = events[0].when
        parent = next((t for when, t in reversed(timeline) if when <= start), None)
        task = self.task_of(" ".join(e.text for e in events[:1])) or parent
        if not task:
            return
        self.day[start.date()]["agents"] += 1
        for e in events:
            if e.kind == "assistant":
                self.tokens[(e.when.date(), task)] += e.tokens
                self.day[e.when.date()]["tokens"] += e.tokens

    def hours(self) -> dict:
        """{источник: {(день, задача): часы}}; пересечения делятся между задачами поровну."""
        points = sorted({p for s, e, _, _ in self.intervals for p in (s, e)})
        index = {p: i for i, p in enumerate(points)}
        active = defaultdict(list)  # номер отрезка → [(задача, источник)]
        for s, e, task, source in self.intervals:
            for i in range(index[s], index[e]):
                active[i].append((task, source))
        result = defaultdict(lambda: defaultdict(float))
        for i, items in active.items():
            start, length = points[i], (points[i + 1] - points[i]).total_seconds() / 3600
            # «сессии» важнее «вне чата»: в окне ожидания шла другая сессия — это работа в ней
            chat = {t for t, s in items if s == "сессии"}
            tasks = chat or {t for t, _ in items}
            source = "сессии" if chat else "вне чата"
            for task in tasks:
                result[source][(start.date(), task)] += length / len(tasks)
        return result

    def resource(self, tokens_per_hour: float) -> dict:
        return {k: v / tokens_per_hour for k, v in self.tokens.items()}


def reflog_estimate(repo: Path, rx: re.Pattern, last_activity: dict) -> dict:
    """{(день, задача): часы} по окнам git reflog, пока выгружена ветка задачи."""
    out = subprocess.run(
        ["git", "-C", str(repo), "reflog", "--date=iso-strict", "--format=%gd|%gs"],
        capture_output=True, text=True, check=False,
    ).stdout.splitlines()
    events = []
    for line in out:
        m = re.match(r".*?\{(.+?)\}\|(.*)", line)
        if not m:
            continue
        when = datetime.fromisoformat(m[1]).astimezone()
        co = re.match(r"checkout: moving from \S+ to (\S+)", m[2])
        events.append((when, co[1] if co else None))
    events.sort(key=lambda e: e[0])
    hours = defaultdict(float)
    branch = None
    for i, (when, to) in enumerate(events):
        if to:
            branch = to
        found = rx.search(branch or "")
        if not found:
            continue
        nxt = events[i + 1][0] if i + 1 < len(events) and events[i + 1][0].date() == when.date() else None
        end = nxt or last_activity.get(when.date(), when)
        if end > when:
            task = f"{found[1].upper()}-{found[2]}"
            hours[(when.date(), task)] += (end - when).total_seconds() / 3600
    return hours


def session_folder(repo: Path) -> str:
    return str(repo.resolve()).replace("/", "-").replace("_", "-")


def repos_for(folders: list[Path]) -> list[Path]:
    """Git-репозитории в CODE_ROOT, чьи сессии выбраны (папка сессий = путь со «-»)."""
    names = {f.name for f in folders}
    return [d for d in sorted(CODE_ROOT.iterdir())
            if (d / ".git").exists() and session_folder(d) in names]


def timesheet_days(path: Path) -> dict:
    """{день: часы} из раздела «Итоги по дням» TIMESHEET.md."""
    days = {}
    for m in re.finditer(r"^\| \S+ (\d\d)\.(\d\d)\.(\d{4}) \| ([\d.]+) \|$",
                         path.read_text(encoding="utf-8"), re.M):
        days[date(int(m[3]), int(m[2]), int(m[1]))] = float(m[4])
    return days


def boot_time() -> datetime:
    """Время загрузки машины по /proc/uptime (для текущего дня)."""
    seconds = float(Path("/proc/uptime").read_text().split()[0])
    return datetime.now().astimezone() - timedelta(seconds=seconds)


def day_window(stats: dict, boot) -> float | None:
    """Часы от первого до последнего события дня; начало — не раньше загрузки машины."""
    if not stats.get("first"):
        return None
    first = max(stats["first"], boot) if boot and boot.date() == stats["first"].date() else stats["first"]
    return max((stats["last"] - first).total_seconds() / 3600, 0)


def scale_day(tasks: dict, total: float) -> dict:
    """Масштабировать часы задач дня до total, шаг STEP, наибольший остаток."""
    raw = sum(tasks.values())
    if raw <= 0:
        return {}
    units = total / STEP
    exact = {t: h / raw * units for t, h in tasks.items()}
    result = {t: int(u) for t, u in exact.items()}
    left = round(units) - sum(result.values())
    for t in sorted(exact, key=lambda t: exact[t] - int(exact[t]), reverse=True)[:left]:
        result[t] += 1
    return {t: u * STEP for t, u in result.items() if u}


def round_day(tasks: dict) -> dict:
    """Округлить до шага, сохранив сумму (наибольший остаток)."""
    return scale_day(tasks, round(sum(tasks.values()) / STEP) * STEP)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--from", dest="date_from", required=True, type=date.fromisoformat)
    parser.add_argument("--to", dest="date_to", required=True, type=date.fromisoformat)
    parser.add_argument("--sessions", type=Path, action="append",
                        help="папка сессий (можно несколько); по умолчанию — все "
                             "из ~/.claude, ~/.claude-zai и ~/.claude-local")
    parser.add_argument("--repo", type=Path, action="append",
                        help="git-репозиторий для reflog; по умолчанию — репозитории выбранных сессий")
    parser.add_argument("--extra", type=Path, help="JSON с дополнительными оценками")
    parser.add_argument("--prefixes", default=DEFAULT_PREFIXES, help="префиксы очередей Трекера")
    parser.add_argument("--full-day", type=float, default=8.0, help="минимум часов в полном дне")
    parser.add_argument("--max-day", type=float, default=10.0, help="предупреждать, если день длиннее")
    parser.add_argument("--cap", action="store_true", help="урезать день до --max-day")
    parser.add_argument("--tokens-per-hour", type=float, default=TOKENS_PER_HOUR,
                        help="выходных токенов на час работы (источник «ресурс»)")
    parser.add_argument("--calibrate", type=Path, metavar="TIMESHEET",
                        help="подобрать --tokens-per-hour по дням табеля и применить")
    parser.add_argument("--partial", action="append", type=date.fromisoformat, default=[],
                        help="неполный день (не масштабировать); сегодня — всегда")
    parser.add_argument("--no-uptime", action="store_true",
                        help="не ограничивать сегодняшнее окно временем загрузки машины")
    parser.add_argument("--json", action="store_true", help="вывод в JSON")
    args = parser.parse_args()

    rx = task_re(args.prefixes.split(","))
    folders = [p.expanduser() for p in args.sessions] if args.sessions else sorted(
        (p for root in SESSION_ROOTS if root.is_dir() for p in root.iterdir() if p.is_dir()),
        key=lambda p: p.name)
    sessions = Sessions(folders, rx)
    boot = None if args.no_uptime else boot_time()

    tokens_per_hour = args.tokens_per_hour
    if args.calibrate:
        ratios = {d: sessions.day[d]["tokens"] / h for d, h in timesheet_days(args.calibrate).items()
                  if h and sessions.day.get(d, {}).get("tokens")}
        if ratios:
            tokens_per_hour = statistics.median(ratios.values())
            spread = ", ".join(f"{d:%d.%m} {r / 1000:.0f}k" for d, r in sorted(ratios.items())[-10:])
            print(f"калибровка: {thousands(tokens_per_hour)} ток./ч по {len(ratios)} дням "
                  f"(последние: {spread})")

    sources = dict(sessions.hours())
    sources["ресурс"] = sessions.resource(tokens_per_hour)
    reflog = defaultdict(float)
    for repo in args.repo or repos_for(folders):
        # окно последней ветки дня закрывается последним событием сессий этого проекта
        last = sessions.last.get(session_folder(repo), {})
        for k, v in reflog_estimate(repo, rx, last).items():
            reflog[k] += v
    sources["reflog"] = reflog
    if args.extra:
        extra = defaultdict(float)
        for item in json.loads(args.extra.read_text(encoding="utf-8")).get("tasks", []):
            extra[(date.fromisoformat(item["date"]), item["task"])] += float(item["hours"])
        sources["extra"] = extra

    days = defaultdict(dict)
    for name, est in sources.items():
        for (day, task), h in est.items():
            if args.date_from <= day <= args.date_to and h > 0:
                days[day].setdefault(task, {})[name] = round(h, 2)

    partial = set(args.partial) | {date.today()}
    report = []
    for day in sorted(days):
        cells = days[day]
        if sum(cells[t].get("сессии", 0) + cells[t].get("ресурс", 0) for t in cells) < STEP / 2 \
                and not any("reflog" in v or "extra" in v for v in cells.values()):
            continue  # случайное событие ночью, не рабочий день
        # время по задаче: сессии + вне чата, либо reflog / extra, что больше
        timed = {t: max(v.get("сессии", 0) + v.get("вне чата", 0), v.get("reflog", 0),
                        v.get("extra", 0)) for t, v in cells.items()}
        spent = {t: v.get("ресурс", 0) for t, v in cells.items()}
        # итог дня — время с поправкой на ресурс модели (среднее, но не меньше времени);
        # доли задач — среднее долей времени и ресурса
        total = max(sum(timed.values()), (sum(timed.values()) + sum(spent.values())) / 2)
        # поправка на ресурс не выводит за окно работы (первое — последнее событие, не раньше загрузки)
        window_hours = day_window(sessions.day.get(day, {}), boot)
        if window_hours is not None:
            total = min(total, max(sum(timed.values()), window_hours))
        weight = {t: (timed[t] / (sum(timed.values()) or 1) + spent[t] / (sum(spent.values()) or 1)) / 2
                  for t in cells}
        best = {t: weight[t] * total for t in cells}
        best = {t: h for t, h in best.items() if h >= STEP / 2}
        total = sum(best.values())
        if day not in partial and total < args.full_day:
            final = scale_day(best, args.full_day)
        elif args.cap and total > args.max_day:
            final = scale_day(best, args.max_day)
        else:
            final = round_day(best)
        stats = sessions.day.get(day, {})
        report.append({
            "date": day.isoformat(),
            "full_day": day not in partial,
            "window": [f"{stats['first']:%H:%M}", f"{stats['last']:%H:%M}"] if stats.get("first") else None,
            "window_hours": round(day_window(stats, boot) or 0, 2),
            "compactions": stats.get("compactions", 0),
            "agents": stats.get("agents", 0),
            "output_tokens": stats.get("tokens", 0),
            "tokens_per_hour": round(tokens_per_hour),
            "tasks": [
                {"task": t, "sources": cells[t], "estimate": round(best.get(t, 0), 2),
                 "hours": final.get(t, 0)}
                for t in sorted(cells, key=lambda t: (-final.get(t, 0), -best.get(t, 0)))
                if final.get(t, 0) or best.get(t, 0)
            ],
            "total": sum(final.values()),
            "over_max": sum(final.values()) > args.max_day,
        })

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    for d in report:
        kind = f"полный, не меньше {args.full_day:g} ч" if d["full_day"] else "неполный"
        window = "–".join(d["window"]) + f" ({d['window_hours']:g} ч)" if d["window"] else "—"
        print(f"\n{d['date']}  ({kind}, итого {d['total']:g} ч)  окно {window}, "
              f"компакций {d['compactions']}, агентов {d['agents']}, "
              f"выход {thousands(d['output_tokens'])} ток.")
        if d["over_max"]:
            print(f"  ! день длиннее {args.max_day:g} ч — проверить перерывы (--cap урежет)")
        for t in d["tasks"]:
            src = ", ".join(f"{k} {v:g}" for k, v in t["sources"].items())
            print(f"  {t['task']:<22} {t['hours']:>5g} ч   оценка {t['estimate']:g} ({src})")


if __name__ == "__main__":
    main()
