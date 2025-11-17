from __future__ import annotations

import os
from typing import List

from src.core.db import get_conn


def _ensure_tracking_table() -> None:
    """Ensure schema_migrations tracking table exists."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists schema_migrations (
                filename text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )


def _read_sql_file(path: str) -> str:
    """Read a SQL file using UTF-8 encoding."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _split_sql_statements(sql: str) -> List[str]:
    """Split SQL text into individual statements terminated by semicolons.

    This simple splitter handles semicolons within single/double-quoted strings.
    It is not a full SQL parser: dollar-quoting and complex constructs may not be
    handled. Suitable for simple DDL/DML migrations without functions/procedures.
    """
    statements: List[str] = []
    buf: list[str] = []

    in_single = False
    in_double = False
    escape = False

    for ch in sql:
        buf.append(ch)

        if ch == "\\":
            # Track escapes inside strings (best-effort)
            escape = not escape
            continue
        else:
            escape = False

        if not in_double and ch == "'" and not escape:
            in_single = not in_single
        elif not in_single and ch == '"' and not escape:
            in_double = not in_double
        elif not in_single and not in_double and ch == ";":
            # End of statement
            stmt = "".join(buf).strip()
            buf.clear()
            if stmt:
                # Drop the trailing semicolon
                statements.append(stmt[:-1].strip())

    # Remainder (if any)
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)

    # Remove empty ones just in case
    return [s for s in statements if s]


# PUBLIC_INTERFACE
def apply_migrations_from_path(migrations_path: str) -> List[str]:
    """Apply .sql migrations from the given path, returning the list of applied filenames.

    The function:
      - Ensures the migration tracking table exists.
      - Sorts *.sql files lexicographically (e.g., 001_..., 002_...).
      - Skips files already recorded in the tracker.
      - Executes each file statement-by-statement in a single transaction.
      - Records the filename in the tracker on success.

    Args:
        migrations_path: Directory path holding .sql migration files.

    Returns:
        List of applied migration filenames (in order).
    """
    if not migrations_path or not os.path.isdir(migrations_path):
        return []

    _ensure_tracking_table()

    files = [f for f in os.listdir(migrations_path) if f.lower().endswith(".sql")]
    files.sort()
    applied: List[str] = []

    for fname in files:
        fpath = os.path.join(migrations_path, fname)
        with get_conn() as conn, conn.cursor() as cur:
            # Skip if already applied
            cur.execute("select 1 from schema_migrations where filename=%s", (fname,))
            if cur.fetchone():
                continue

            # Read and split SQL script, then execute statements sequentially
            sql_text = _read_sql_file(fpath)
            for stmt in _split_sql_statements(sql_text):
                cur.execute(stmt)

            # Record success
            cur.execute("insert into schema_migrations (filename) values (%s)", (fname,))
            applied.append(fname)

    return applied
