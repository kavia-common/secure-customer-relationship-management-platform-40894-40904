from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

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
    status: str = Field(..., description="Draft/Published")
    version: int = Field(..., description="Workflow version")
    published_at: Optional[str] = Field(None, description="Published timestamp")


class WorkflowKeyIn(BaseModel):
    key: str = Field(..., description="Workflow key")


class WorkflowTestIn(BaseModel):
    key: str = Field(..., description="Workflow key")
    input: Dict[str, Any] = Field(default_factory=dict, description="Test input")


def _ensure_table() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists workflows (
                id bigserial primary key,
                key text not null unique,
                definition jsonb not null default '{}'::jsonb,
                status text not null default 'draft',
                version int not null default 1,
                published_at timestamptz null,
                created_at timestamptz not null default now()
            )
            """
        )
        # ensure columns exist if table was created previously without them
        cur.execute("alter table workflows add column if not exists status text not null default 'draft'")
        cur.execute("alter table workflows add column if not exists version int not null default 1")
        cur.execute("alter table workflows add column if not exists published_at timestamptz null")


@router.post("", summary="Upsert workflow", response_model=WorkflowOut, dependencies=[Depends(require_role("admin"))])
def upsert_workflow(payload: WorkflowIn, request: Request, user=Depends(get_current_user)) -> WorkflowOut:
    """Create or update a workflow definition by key (kept for compatibility)."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into workflows (key, definition)
            values (%s, %s::jsonb)
            on conflict (key) do update set definition=excluded.definition
            returning id, key, definition, status, version, published_at
            """,
            (payload.key, json.dumps(payload.definition or {})),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Upsert failed")
        out = WorkflowOut(id=int(r[0]), key=r[1], definition=r[2] or {}, status=r[3], version=int(r[4]), published_at=(r[5].isoformat() if r[5] else None))
    audit_log("upsert", "workflow", out.id, {"key": payload.key}, user.get("id"), request.client.host if request.client else None)
    return out


@router.post("/draft", summary="Create/update draft workflow", response_model=WorkflowOut, dependencies=[Depends(require_role("admin"))])
def draft_workflow(payload: WorkflowIn, request: Request, user=Depends(get_current_user)) -> WorkflowOut:
    """Create or update a workflow draft."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into workflows (key, definition, status)
            values (%s, %s::jsonb, 'draft')
            on conflict (key) do update set definition=excluded.definition, status='draft'
            returning id, key, definition, status, version, published_at
            """,
            (payload.key, json.dumps(payload.definition or {})),
        )
        r = cur.fetchone()
        out = WorkflowOut(id=int(r[0]), key=r[1], definition=r[2] or {}, status=r[3], version=int(r[4]), published_at=(r[5].isoformat() if r[5] else None))
    audit_log("draft", "workflow", out.id, {"key": payload.key}, user.get("id"), request.client.host if request.client else None)
    return out


@router.post("/publish", summary="Publish workflow", response_model=WorkflowOut, dependencies=[Depends(require_role("admin"))])
def publish_workflow(payload: WorkflowKeyIn, request: Request, user=Depends(get_current_user)) -> WorkflowOut:
    """Publish a workflow (increments version and sets status=published)."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update workflows
            set status='published', version=coalesce(version,1)+1, published_at=now()
            where key=%s
            returning id, key, definition, status, version, published_at
            """,
            (payload.key,),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        out = WorkflowOut(id=int(r[0]), key=r[1], definition=r[2] or {}, status=r[3], version=int(r[4]), published_at=(r[5].isoformat() if r[5] else None))
    audit_log("publish", "workflow", out.id, {"key": payload.key}, user.get("id"), request.client.host if request.client else None)
    return out


@router.post("/test", summary="Test workflow", response_model=dict, dependencies=[Depends(require_role("admin"))])
def test_workflow(payload: WorkflowTestIn, user=Depends(get_current_user)) -> Dict[str, Any]:
    """Test a workflow run (stub)."""
    # In a real engine, we'd interpret the definition and run; return stub response for now.
    return {"ok": True, "key": payload.key, "input_echo": payload.input}


@router.get("", summary="List workflows", response_model=List[WorkflowOut])
def list_workflows(user=Depends(get_current_user)) -> List[WorkflowOut]:
    """List workflow definitions."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select id, key, definition, status, version, published_at from workflows order by key")
        rows = cur.fetchall() or []
        out: List[WorkflowOut] = []
        for r in rows:
            out.append(
                WorkflowOut(
                    id=int(r[0]),
                    key=r[1],
                    definition=r[2] or {},
                    status=r[3],
                    version=int(r[4]),
                    published_at=(r[5].isoformat() if r[5] else None),
                )
            )
        return out
