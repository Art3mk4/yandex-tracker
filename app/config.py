"""Конфигурация приложения (переменные окружения)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    database_url: str = "postgresql://timesheet:timesheet@localhost:5432/timesheet"
    timesheet_path: Path = Path("TIMESHEET.md")
    auto_import_on_empty: bool = True

    # Зеркало Яндекс Трекера (TRACKER_ORG_ID — X-Org-ID организации, из env)
    tracker_token_file: Path = Path("/srv/secrets/tracker_token")
    tracker_org_id: str = ""
    tracker_base_url: str = "https://api.tracker.yandex.net/v3"
    attachments_dir: Path = Path("/srv/data/attachments")
    public_base_url: str = "http://127.0.0.1:8787"


settings = Settings()
