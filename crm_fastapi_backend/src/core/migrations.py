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


# PUBLIC_INTERFACE
def apply_migrations_from_path(migrations_path: str) -> List[str]:
    """Apply .sql migrations from the given path, returning the list of applied filenames."""
    if not migrations_path or not os.path.isdir(migrations_path):
        return []

    _ensure_tracking_table()

    files = [f for f in os.listdir(migrations_path) if f.lower().endswith(".sql")]
    files.sort()
    applied: List[str] = []

    for fname in files:
        fpath = os.path.join(migrations_path, fname)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("select 1 from schema_migrations where filename=%s", (fname,))
            if cur.fetchone():
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                sql = f.read()
            cur.execute(sql)
            cur.execute("insert into schema_migrations (filename) values (%s)", (fname,))
            applied.append(fname)

    return applied
