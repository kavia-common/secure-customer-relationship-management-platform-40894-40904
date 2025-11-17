from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.core.audit import audit_log
from src.core.auth import get_current_user, require_role
from src.core.db import get_conn

router = APIRouter(prefix="/workflows", tags=["Workflows"])


class WorkflowIn(BaseModel):
    key: str = Field(..., description="Unique workflow key")
    definition: Dict[str, Any] = Field(default_factory=dict, description="Workflow definition JSON")


class WorkflowOut(WorkflowIn):
    id: int = Field(..., description="Workflow ID")


def _ensure_table() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists workflows (
                id bigserial primary key,
                key text not null unique,
                definition jsonb not null default '{}'::jsonb,
                created_at timestamptz not null default now()
            )
            """
        )


@router.post("", summary="Upsert workflow", response_model=WorkflowOut)
def upsert_workflow(payload: WorkflowIn, request: Request, user=Depends(require_role("admin"))) -> WorkflowOut:
    """Create or update a workflow definition by key."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into workflows (key, definition)
            values (%s, %s::jsonb)
            on conflict (key) do update set definition=excluded.definition
            returning id, key, definition
            """,
            (payload.key, json.dumps(payload.definition or {})),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Upsert failed")
        out = WorkflowOut(id=int(r[0]), key=r[1], definition=r[2] or {})
    audit_log("upsert", "workflow", out.id, {"key": payload.key}, user.get("id"), request.client.host if request.client else None)
    return out


@router.get("", summary="List workflows", response_model=List[WorkflowOut])
def list_workflows(user=Depends(get_current_user)) -> List[WorkflowOut]:
    """List workflow definitions."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select id, key, definition from workflows order by key")
        rows = cur.fetchall() or []
        return [WorkflowOut(id=int(r[0]), key=r[1], definition=r[2] or {}) for r in rows]
