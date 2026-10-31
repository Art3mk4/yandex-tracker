"""Подключение к Postgres (psycopg 3).

Локальный однопользовательский дашборд: соединение открывается на запрос,
пула нет намеренно — меньше состояния и проблем с жизненным циклом
(например, в `docker compose run --rm app python -m app.import_timesheet`).
"""
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from app.config import settings


@contextmanager
def connect():
    """Соединение с БД как context manager; строки — словари."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn
