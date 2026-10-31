"""FastAPI-приложение: API + MCP + статика SPA (собирается в Docker).

Запуск: uvicorn app.main:app --host 0.0.0.0 --port 8080
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import api
from app.config import settings
from app.mcp_server import mcp

log = logging.getLogger("timesheet")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

mcp_app = mcp.http_app(path="/mcp")  # путь внутри монтирования /mcp → /mcp/mcp
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def maybe_auto_import() -> None:
    """Импорт табеля при пустой БД (первый запуск контейнера)."""
    if not settings.auto_import_on_empty:
        return
    try:
        from app.db import connect
        from app.import_timesheet import run_import

        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('time_entries') AS t")
            if cur.fetchone()["t"] is None:
                log.warning("time_entries нет — проверьте монтирование db/init")
                return
            cur.execute("SELECT count(*) AS n FROM time_entries")
            if cur.fetchone()["n"] > 0:
                return
        result = run_import(dry_run=False)
        log.info("автоимпорт: записей %s, часов %g", result.total_rows, result.total_hours)
    except Exception:  # noqa: BLE001 — автозапуск не должен ронять приложение
        log.exception("автоимпорт не удался")


@asynccontextmanager
async def lifespan(app: FastAPI):
    maybe_auto_import()
    async with mcp_app.lifespan(app):  # менеджер сессий MCP
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="Timesheet", lifespan=lifespan)
    app.include_router(api.router)
    app.mount("/mcp", mcp_app)
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="spa")
    return app


app = create_app()
