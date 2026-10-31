# yandex-tracker — учёт времени и локальное зеркало Яндекс Трекера

Личный инструмент учёта рабочего времени и резервная копия задач из Яндекс Трекера:

```
сессии Claude Code (~/.claude/projects) + git reflog
        │  estimate.py — черновик часов по дням и задачам
        ▼
TIMESHEET.md — табель (markdown, источник истины)
        │  timesheet_to_tracker.py / MCP yandex-tracker
        ▼
ворклоги в Яндекс Трекере

TIMESHEET.md ──import──▶ Postgres ──▶ FastAPI + Vue SPA (дашборд)
Яндекс Трекер ──sync──▶  │            └─ MCP-сервер (табель + зеркало)
(API, OAuth)             └─ зеркало: задачи, комментарии, история, файлы
```

Три независимые части:

1. **Скрипты табеля** (чистый Python 3.10+, без зависимостей): оценка часов по локальным
   источникам → markdown-табель → ворклоги в Трекер (MCP или генерируемый `sync.js`
   для консоли браузера).
2. **Дашборд** (Docker): Postgres + FastAPI + Vue 3 — график часов по дням, топ задач,
   таблица с фильтрами.
3. **Зеркало Трекера** (Docker): локальная копия задач — карточки, комментарии,
   история изменений, вложения — с доступом через веб-страницу и MCP. Если Трекер
   недоступен, история работы остаётся с вами.

## Быстрый старт

1. **Предусловия**: Docker + Compose; свободные порты 55432 (БД) и 8787 (приложение);
   OAuth-токен Яндекс Трекера (см. [документацию](https://yandex.ru/support/tracker/ru/concepts/access),
   права `tracker:read`/`tracker:write`) в файле с режимом 0600.
2. **Конфиг**:
   ```bash
   cp .env.example .env            # заполнить POSTGRES_PASSWORD, TRACKER_TOKEN_HOST_FILE, TRACKER_ORG_ID
   ```
3. **Проекты для табеля** — локальный `projects.json` (не в git):
   ```json
   [{"code": "my-project", "sessions_path": "~/.claude/projects/…", "since": "2026-01-01"}]
   ```
4. **Каталог вложений зеркала** (пишет контейнер под другим uid):
   ```bash
   mkdir -p data/attachments && chmod 777 data/attachments
   ```
5. **Запуск**: `docker compose up -d --build` → `docker compose ps`: db и app healthy.
   Свежий том: схемы и автоимпорт табеля выполняются сами.
6. **Первый синк зеркала**:
   ```bash
   docker compose run --rm --user "$(id -u):$(id -g)" app python -m app.tracker_sync
   ```
7. **MCP для Claude Code** (`entries_for_day`, `search_issues`, `get_issue`):
   ```bash
   claude mcp add --transport http timesheet http://127.0.0.1:8787/mcp/mcp
   ```
8. **Проверка**: `curl -s 127.0.0.1:8787/api/health`; дашборд http://127.0.0.1:8787;
   задачи зеркала http://127.0.0.1:8787/#/tasks.

## Повседневные команды

```bash
# черновик часов за день (сессии всех проектов + git reflog)
python3 estimate.py --from 2026-01-01 --to 2026-01-01 --calibrate TIMESHEET.md

# табель → Трекер (генерирует sync.js для консоли https://tracker.yandex.ru)
python3 timesheet_to_tracker.py --parse-only          # что прочиталось
python3 timesheet_to_tracker.py [--task KEY-123]      # dry-run
python3 timesheet_to_tracker.py --task KEY-123 --apply

# табель → БД дашборда (идемпотентно)
docker compose run --rm app python -m app.import_timesheet --dry-run
docker compose run --rm app python -m app.import_timesheet

# зеркало Трекера: инкремент / одна задача / полный перечит
docker compose run --rm --user "$(id -u):$(id -g)" app python -m app.tracker_sync
docker compose run --rm --user "$(id -u):$(id -g)" app python -m app.tracker_sync --issue KEY-123
docker compose run --rm --user "$(id -u):$(id -g)" app python -m app.tracker_sync --full
```

`--user` у синка — чтобы контейнер читал токен (0600) и писал файлы от вашего uid.
Порядок событий дня: оценка → запись в табель → импорт в БД → ворклоги в Трекер → синк зеркала.

## Устройство

| Путь | Что |
|---|---|
| `estimate.py` | черновик часов: сессии Claude Code (в чате, вне чата, ресурс модели), git reflog, `--extra` |
| `timesheet_to_tracker.py` | разбор табеля (`parse_rows`) → `timesheet.json` + `sync.js` |
| `sync-core.js` | логика записи ворклогов (общая для консоли и extension) |
| `app/` | FastAPI: API (`api.py`), импорт (`import_timesheet.py`), синк зеркала (`tracker_sync.py`), MCP (`mcp_server.py`) |
| `db/init/` | SQL-схемы: табель (001) и зеркало (002), идемпотентные |
| `frontend/` | Vue 3 + Vite + Chart.js: дашборд и вкладка задач зеркала |
| `TIMESHEET.md`, `.env`, `projects.json`, `data/` | локальные данные — в `.gitignore`, не публикуются |

API зеркала: `GET /api/issues?q=&queue=`, `GET /api/issues/{key}` (карточка,
комментарии, вложения, история), `GET /api/attachments/{id}/download`,
`GET /api/mirror/status`.

## Находки про API Яндекс Трекера

Всё проверено на живом API (v3), сэкономит часы отладки:

- Поиск задач — `POST /issues/_search` (не `/_search`) с телом `{"query": "…"}`;
  фильтр автора — `author: login` (не `createdBy`).
- Списки (комментарии, changelog, вложения) листаются **курсором из заголовка
  `Link: rel="next"`** (параметр `id`); параметр `page` молча игнорируется.
- Длительности хранятся в «рабочих единицах»: 8 ч возвращается как `P1D`
  (1 д = 8 ч, 1 н = 5 д) — сравнивать в минутах.
- Типы ID непоследовательны: комментарии — числа, changelog — hex-строки,
  вложения — строки из цифр.
- Веб-интерфейс Трекера ходит в тот же `/api/public/v3` с сессией браузера —
  `fetch(url, {credentials: 'include'})` из вкладки работает без токена.

## Дальше

- БД как источник истины вместо markdown (экспорт табеля, запись через приложение/MCP);
- Chrome extension: кнопка «синхронизировать» вместо вставки `sync.js` в консоль;
- запись из Трекера в БД (ворклоги → `tracker_worklog_id`).
