from __future__ import annotations

import os
from functools import lru_cache
from typing import List


class Settings:
    """Application configuration loaded from environment variables.

    Safe defaults are provided for local development only. For production,
    explicit environment variables should be supplied at deploy time.
    """

    # App metadata
    app_name: str
    app_version: str

    # Server
    backend_port: int

    # Database
    database_url: str | None

    # Auth/session
    token_ttl_seconds: int

    # CORS
    cors_origins: List[str]

    # Rate limiting
    rate_limit_per_minute: int
    # Backwards-compat fields used in existing code paths
    rate_limit_requests: int
    rate_limit_window_seconds: int

    # Migrations
    migrations_path: str

    # Feature flags
    audit_enabled: bool

    def __init__(self) -> None:
        # App metadata
        self.app_name = os.getenv("APP_NAME", "CRM FastAPI Backend")
        self.app_version = os.getenv("APP_VERSION", "0.1.0")

        # Server binding
        # BACKEND_PORT: default 3001
        self.backend_port = int(os.getenv("BACKEND_PORT", "3001"))

        # Database
        # DATABASE_URL: no production default; dev-friendly None allows degraded mode
        # Example: postgresql://user:pass@host:5432/db
        self.database_url = os.getenv("DATABASE_URL") or None

        # Auth/session
        # TOKEN_TTL_SECONDS: default 3600
        self.token_ttl_seconds = int(os.getenv("TOKEN_TTL_SECONDS", "3600"))

        # CORS: CSV list defaulting to http://localhost:3000
        cors_raw = os.getenv("CORS_ALLOW_ORIGINS") or os.getenv("CORS_ORIGINS", "http://localhost:3000")
        self.cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]

        # Rate limiting
        # RATE_LIMIT_PER_MINUTE: default 120
        self.rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
        # Backwards compatibility for existing middleware usage:
        self.rate_limit_requests = self.rate_limit_per_minute
        self.rate_limit_window_seconds = 60

        # Migrations
        # MIGRATIONS_PATH: default "migrations"
        self.migrations_path = os.getenv("MIGRATIONS_PATH", "migrations")

        # Feature flags (keep simple truthy parsing)
        self.audit_enabled = os.getenv("AUDIT_ENABLED", "true").lower() in {"1", "true", "yes"}


# PUBLIC_INTERFACE
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Use this accessor instead of constructing Settings directly to
    avoid repeated environment reads and to support memoization.
    """
    return Settings()
