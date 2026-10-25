from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KPD_", env_file=".env", extra="ignore")
    app_name: str = "КПД производства квадрокоптеров — ДЕМО"
    environment: str = "demo"
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'demo.db').as_posix()}"
    session_cookie_name: str = "kpd_demo_session"
    session_hours: int = 12
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

