import os
from functools import lru_cache
from typing import List


class Settings:
    """Application configuration loaded from environment variables."""

    app_name: str
    app_version: str
    database_url: str | None
    cors_origins: List[str]
    rate_limit_requests: int
    rate_limit_window_seconds: int
    token_ttl_seconds: int
    migrations_path: str | None
    audit_enabled: bool

    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "CRM FastAPI Backend")
        self.app_version = os.getenv("APP_VERSION", "0.1.0")
        self.database_url = os.getenv("DATABASE_URL")  # Example: postgresql://user:pass@host:5432/db
        cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        self.cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        self.rate_limit_requests = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
        self.rate_limit_window_seconds = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
        self.token_ttl_seconds = int(os.getenv("TOKEN_TTL_SECONDS", "3600"))
        self.migrations_path = os.getenv("MIGRATIONS_PATH")  # Path mounted with SQL migration files (from DB container)
        self.audit_enabled = os.getenv("AUDIT_ENABLED", "true").lower() in {"1", "true", "yes"}


# PUBLIC_INTERFACE
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
