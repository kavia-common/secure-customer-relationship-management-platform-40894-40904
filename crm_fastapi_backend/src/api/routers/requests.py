from __future__ import annotations

import json
import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from src.core.audit import audit_log
from src.core.auth import get_current_user
from src.core.db import get_conn

router = APIRouter(prefix="/requests", tags=["Requests"])

VALID_STATUSES = ["open", "assigned", "in_progress", "escalated", "resolved", "closed"]


class RequestIn(BaseModel):
    customer_id: int = Field(..., description="Customer ID")
    subject: str = Field(..., description="Subject/title")
    description: str = Field(..., description="Description")
    priority: str = Field("normal", description="Priority (low/normal/high)")
    meta: Optional[dict] = Field(default_factory=dict, description="Additional metadata")


class RequestPatch(BaseModel):
    subject: Optional[str] = Field(None, description="Subject/title")
    description: Optional[str] = Field(None, description="Description")
    priority: Optional[str] = Field(None, description="Priority (low/normal/high)")
    meta: Optional[dict] = Field(None, description="Additional metadata")
    assignee_id: Optional[int] = Field(None, description="Assigned agent id")


class RequestOut(RequestIn):
    id: int = Field(..., description="Request ID")
    status: str = Field(..., description="Current status")
    # Optional fields that may exist
    assignee_id: Optional[int] = Field(None, description="Assigned agent id")


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
                assignee_id bigint null,
                sla_due_at timestamptz null,
                created_by bigint null,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now()
            )
            """
        )
        # Ensure new columns exist if table was created previously
        cur.execute("alter table requests add column if not exists assignee_id bigint null")
        cur.execute("alter table requests add column if not exists sla_due_at timestamptz null")
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


# PUBLIC_INTERFACE
@router.post("", summary="Create request", response_model=RequestOut, status_code=201)
def create_request(payload: RequestIn, request: Request, user=Depends(get_current_user)) -> RequestOut:
    """Create a service request."""
    _ensure_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into requests (customer_id, subject, description, status, priority, meta, created_by)
            values (%s, %s, %s, 'open', %s, %s::jsonb, %s)
            returning id, customer_id, subject, description, status, priority, meta, assignee_id
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
            assignee_id=r[7],
        )
    audit_log("create", "request", out.id, {"customer_id": payload.customer_id}, user.get("id"), request.client.host if request.client else None)
    return out


# PUBLIC_INTERFACE
@router.get("", summary="List requests", response_model=List[RequestOut])
def list_requests(
    status_q: Optional[str] = Query(None, alias="status", description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    assignee: Optional[int] = Query(None, description="Filter by assignee id"),
    customer_id: Optional[int] = Query(None, description="Filter by customer id"),
    start: Optional[str] = Query(None, description="Start ISO timestamp"),
    end: Optional[str] = Query(None, description="End ISO timestamp"),
    sla: Optional[str] = Query(None, description="SLA filter (breached)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
) -> List[RequestOut]:
    """List requests with rich filters and pagination."""
    _ensure_tables()
    conditions = []
    params = []
    if status_q:
        conditions.append("status=%s")
        params.append(status_q)
    if priority:
        conditions.append("priority=%s")
        params.append(priority)
    if assignee is not None:
        conditions.append("assignee_id=%s")
        params.append(assignee)
    if customer_id is not None:
        conditions.append("customer_id=%s")
        params.append(customer_id)
    if start:
        conditions.append("created_at >= %s")
        params.append(dt.datetime.fromisoformat(start))
    if end:
        conditions.append("created_at <= %s")
        params.append(dt.datetime.fromisoformat(end))
    if sla and sla.lower() == "breached":
        conditions.append("sla_due_at is not null and sla_due_at < now() and status not in ('resolved','closed')")
    where = f"where {' and '.join(conditions)}" if conditions else ""
    offset = (page - 1) * page_size
    sql = f"""
        select id, customer_id, subject, description, status, priority, meta, assignee_id
        from requests
        {where}
        order by updated_at desc
        limit %s offset %s
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (*params, page_size, offset))
        rows = cur.fetchall() or []
        return [
            RequestOut(
                id=int(r[0]),
                customer_id=int(r[1]),
                subject=r[2],
                description=r[3],
                status=r[4],
                priority=r[5],
                meta=r[6] or {},
                assignee_id=r[7],
            )
            for r in rows
        ]


# PUBLIC_INTERFACE
@router.get("/{request_id}", summary="Get request", response_model=RequestOut)
def get_request(request_id: int, user=Depends(get_current_user)) -> RequestOut:
    """Get a single request by id."""
    _ensure_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, customer_id, subject, description, status, priority, meta, assignee_id from requests where id=%s",
            (request_id,),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        return RequestOut(
            id=int(r[0]),
            customer_id=int(r[1]),
            subject=r[2],
            description=r[3],
            status=r[4],
            priority=r[5],
            meta=r[6] or {},
            assignee_id=r[7],
        )


# PUBLIC_INTERFACE
@router.patch("/{request_id}", summary="Patch request", response_model=RequestOut)
def patch_request(request_id: int, payload: RequestPatch, request: Request, user=Depends(get_current_user)) -> RequestOut:
    """Patch request fields (subject, description, priority, meta, assignee)."""
    _ensure_tables()
    updates = []
    params = []
    if payload.subject is not None:
        updates.append("subject=%s")
        params.append(payload.subject)
    if payload.description is not None:
        updates.append("description=%s")
        params.append(payload.description)
    if payload.priority is not None:
        updates.append("priority=%s")
        params.append(payload.priority)
    if payload.meta is not None:
        updates.append("meta=%s::jsonb")
        params.append(json.dumps(payload.meta))
    if payload.assignee_id is not None:
        updates.append("assignee_id=%s")
        params.append(payload.assignee_id)
        # set status to assigned if currently open
        updates.append("status=case when status='open' then 'assigned' else status end")
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No changes provided")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"update requests set {', '.join(updates)}, updated_at=now() where id=%s returning id, customer_id, subject, description, status, priority, meta, assignee_id",
            (*params, request_id),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        out = RequestOut(
            id=int(r[0]),
            customer_id=int(r[1]),
            subject=r[2],
            description=r[3],
            status=r[4],
            priority=r[5],
            meta=r[6] or {},
            assignee_id=r[7],
        )
    audit_log("update", "request", request_id, {"fields": list(payload.model_dump(exclude_none=True).keys())}, user.get("id"), request.client.host if request.client else None)
    return out


# PUBLIC_INTERFACE
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


# PUBLIC_INTERFACE
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


# PUBLIC_INTERFACE
@router.post("/{request_id}/close", summary="Close request", response_model=HistoryOut)
def close_request(request_id: int, request: Request, user=Depends(get_current_user)) -> HistoryOut:
    """Close a request and add a history event."""
    return transition_request(request_id, TransitionIn(to_status="closed", note="closed"), request, user)


# PUBLIC_INTERFACE
@router.post("/{request_id}/escalate", summary="Escalate request", response_model=HistoryOut)
def escalate_request(request_id: int, request: Request, user=Depends(get_current_user)) -> HistoryOut:
    """Escalate a request and add a history event."""
    return transition_request(request_id, TransitionIn(to_status="escalated", note="escalated"), request, user)
