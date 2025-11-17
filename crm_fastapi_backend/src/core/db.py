from __future__ import annotations

import contextlib
from typing import Iterator, Optional

import psycopg
from psycopg_pool import ConnectionPool

from src.core.config import get_settings

_pool: Optional[ConnectionPool] = None


def _create_pool() -> Optional[ConnectionPool]:
    """Create a new psycopg connection pool if DATABASE_URL is configured."""
    settings = get_settings()
    if not settings.database_url:
        return None
    return ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        kwargs={"autocommit": False},
        timeout=10,
        max_idle=60,
        name="crm-db-pool",
    )


# PUBLIC_INTERFACE
def get_pool() -> Optional[ConnectionPool]:
    """Get the global connection pool if initialized, else None."""
    return _pool


# PUBLIC_INTERFACE
def init_pool() -> None:
    """Initialize the global connection pool."""
    global _pool
    if _pool is None:
        _pool = _create_pool()


# PUBLIC_INTERFACE
def close_pool() -> None:
    """Close the global connection pool."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# PUBLIC_INTERFACE
@contextlib.contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Context manager yielding a DB connection from the pool, with safe cleanup."""
    pool = get_pool()
    if pool is None:
        raise RuntimeError("Database pool not initialized or DATABASE_URL not set.")
    with pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            # Ensure rollback on error for safety
            conn.rollback()
            raise
