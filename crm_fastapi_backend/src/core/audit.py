from __future__ import annotations

import json
from typing import Any, Optional

from src.core.db import get_conn
from src.core.config import get_settings


# PUBLIC_INTERFACE
def audit_log(
    action: str,
    resource: str,
    resource_id: Optional[int],
    details: dict[str, Any] | None,
    user_id: Optional[int],
    ip: Optional[str],
) -> None:
    """Persist an audit log entry if auditing is enabled."""
    if not get_settings().audit_enabled:
        return
    payload = json.dumps(details or {})
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists audit_log (
                    id bigserial primary key,
                    user_id bigint null,
                    action text not null,
                    resource text not null,
                    resource_id bigint null,
                    details jsonb not null default '{}'::jsonb,
                    ip text null,
                    created_at timestamptz not null default now()
                )
                """
            )
            cur.execute(
                """
                insert into audit_log (user_id, action, resource, resource_id, details, ip)
                values (%s, %s, %s, %s, %s::jsonb, %s)
                """,
                (user_id, action, resource, resource_id, payload, ip),
            )
    except Exception:
        # Intentionally swallow to avoid impacting business flow; do not leak sensitive info
        return
