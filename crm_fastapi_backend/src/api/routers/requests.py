from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.core.audit import audit_log
from src.core.auth import get_current_user
from src.core.db import get_conn

router = APIRouter(prefix="/requests", tags=["Requests"])

VALID_STATUSES = ["open", "in_progress", "resolved", "closed"]


class RequestIn(BaseModel):
    customer_id: int = Field(..., description="Customer ID")
    subject: str = Field(..., description="Subject/title")
    description: str = Field(..., description="Description")
    priority: str = Field("normal", description="Priority (low/normal/high)")
    meta: Optional[dict] = Field(default_factory=dict, description="Additional metadata")


class RequestOut(RequestIn):
    id: int = Field(..., description="Request ID")
    status: str = Field(..., description="Current status")


class TransitionIn(BaseModel):
    to_status: str = Field(..., description="Target status")
    note: Optional[str] = Field(None, description="Transition note")


class HistoryOut(BaseModel):
    id: int
    request_id: int
    from_status: Optional[str]
    to_status: str
    note: Optional[str]


def _ensure_tables() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists requests (
                id bigserial primary key,
                customer_id bigint not null references customers(id) on delete restrict,
                subject text not null,
                description text not null,
                status text not null default 'open',
                priority text not null default 'normal',
                meta jsonb not null default '{}'::jsonb,
                created_by bigint null,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            """
            create table if not exists request_history (
                id bigserial primary key,
                request_id bigint not null references requests(id) on delete cascade,
                from_status text null,
                to_status text not null,
                note text null,
                changed_by bigint null,
                changed_at timestamptz not null default now()
            )
            """
        )


@router.post("", summary="Create request", response_model=RequestOut, status_code=201)
def create_request(payload: RequestIn, request: Request, user=Depends(get_current_user)) -> RequestOut:
    """Create a service request."""
    _ensure_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into requests (customer_id, subject, description, status, priority, meta, created_by)
            values (%s, %s, %s, 'open', %s, %s::jsonb, %s)
            returning id, customer_id, subject, description, status, priority, meta
            """,
            (payload.customer_id, payload.subject, payload.description, payload.priority, json.dumps(payload.meta or {}), user.get("id")),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Insert failed")
        req_id = int(r[0])
        cur.execute(
            "insert into request_history (request_id, from_status, to_status, note, changed_by) values (%s, %s, %s, %s, %s)",
            (req_id, None, "open", "created", user.get("id")),
        )
        out = RequestOut(
            id=req_id,
            customer_id=int(r[1]),
            subject=r[2],
            description=r[3],
            status=r[4],
            priority=r[5],
            meta=r[6] or {},
        )
    audit_log("create", "request", out.id, {"customer_id": payload.customer_id}, user.get("id"), request.client.host if request.client else None)
    return out


@router.post("/{request_id}/transition", summary="Change request status", response_model=HistoryOut)
def transition_request(request_id: int, payload: TransitionIn, request: Request, user=Depends(get_current_user)) -> HistoryOut:
    """Transition request status and record history."""
    if payload.to_status not in VALID_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
    _ensure_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select status from requests where id=%s", (request_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        from_status = r[0]
        cur.execute(
            "update requests set status=%s, updated_at=now() where id=%s returning status",
            (payload.to_status, request_id),
        )
        cur.execute(
            "insert into request_history (request_id, from_status, to_status, note, changed_by) values (%s, %s, %s, %s, %s) returning id",
            (request_id, from_status, payload.to_status, payload.note, user.get("id")),
        )
        hid = int(cur.fetchone()[0])
        out = HistoryOut(id=hid, request_id=request_id, from_status=from_status, to_status=payload.to_status, note=payload.note)
    audit_log("transition", "request", request_id, {"from": from_status, "to": payload.to_status}, user.get("id"), request.client.host if request.client else None)
    return out


@router.get("/{request_id}/history", summary="Request history", response_model=List[HistoryOut])
def get_history(request_id: int, user=Depends(get_current_user)) -> List[HistoryOut]:
    """Return history records for a request."""
    _ensure_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, request_id, from_status, to_status, note from request_history where request_id=%s order by id",
            (request_id,),
        )
        rows = cur.fetchall() or []
        return [
            HistoryOut(id=int(r[0]), request_id=int(r[1]), from_status=r[2], to_status=r[3], note=r[4])
            for r in rows
        ]
