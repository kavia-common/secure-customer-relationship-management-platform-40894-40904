from __future__ import annotations

import contextlib
from typing import Any, Iterator, Mapping, Optional, Sequence

import psycopg
from psycopg_pool import ConnectionPool

from src.core.config import get_settings

_pool: Optional[ConnectionPool] = None


def _create_pool() -> Optional[ConnectionPool]:
    """Create a new psycopg connection pool if DATABASE_URL is configured.

    Uses conservative defaults suitable for small deployments and tests.
    """
    settings = get_settings()
    if not settings.database_url:
        return None
    # Avoid passing optional args that may vary across psycopg_pool versions.
    # Autocommit is False by default; we commit/rollback explicitly in get_conn().
    return ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        timeout=10,
    )


# PUBLIC_INTERFACE
def get_pool() -> Optional[ConnectionPool]:
    """Get the global connection pool if initialized, else None."""
    return _pool


# PUBLIC_INTERFACE
def init_pool() -> None:
    """Initialize the global connection pool.

    Safe to call multiple times; pool is created once.
    """
    global _pool
    if _pool is None:
        _pool = _create_pool()


# PUBLIC_INTERFACE
def close_pool() -> None:
    """Close the global connection pool and reset the global reference."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# PUBLIC_INTERFACE
@contextlib.contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Context manager yielding a DB connection from the pool, with safe cleanup.

    The connection is committed on successful exit and rolled back on exceptions.
    """
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


# PUBLIC_INTERFACE
def execute(sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> int:
    """Execute a SQL statement and return the affected row count.

    This helper opens a connection and cursor internally and commits on success.

    Args:
        sql: The SQL statement to execute.
        params: Optional parameters sequence or mapping.

    Returns:
        The number of rows affected, if available; otherwise 0.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        return int(cur.rowcount or 0)


# PUBLIC_INTERFACE
def fetchone(sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> Optional[tuple]:
    """Execute a query and return the first row or None."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        return cur.fetchone()


# PUBLIC_INTERFACE
def fetchall(sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> list[tuple]:
    """Execute a query and return all rows as a list of tuples."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        rows = cur.fetchall()
        return list(rows or [])


# PUBLIC_INTERFACE
def fetchval(
    sql: str,
    params: Sequence[Any] | Mapping[str, Any] | None = None,
    default: Any | None = None,
) -> Any:
    """Execute a query and return the first column of the first row or default.

    Args:
        sql: The SQL statement to execute.
        params: Optional parameters.
        default: Value to return if no row is found.

    Returns:
        The value of the first column of the first row, or default.
    """
    row = fetchone(sql, params)
    return row[0] if row and len(row) > 0 else default
