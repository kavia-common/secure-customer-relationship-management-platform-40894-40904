from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from src.core.audit import audit_log
from src.core.auth import get_current_user
from src.core.db import get_conn

router = APIRouter(prefix="/interactions", tags=["Interactions"])


class InteractionIn(BaseModel):
    customer_id: int = Field(..., description="Customer ID")
    type: str = Field(..., description="Interaction type (call, email, chat)")
    channel: str = Field(..., description="Channel (CTI, social, bot, etc.)")
    content: str = Field(..., description="Content/body")
    meta: Optional[dict] = Field(default_factory=dict, description="Additional metadata")


class InteractionOut(InteractionIn):
    id: int = Field(..., description="Interaction ID")


def _ensure_table() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists interactions (
                id bigserial primary key,
                customer_id bigint not null references customers(id) on delete cascade,
                type text not null,
                channel text not null,
                content text not null,
                meta jsonb not null default '{}'::jsonb,
                created_by bigint null,
                created_at timestamptz not null default now()
            )
            """
        )


@router.post("", summary="Create interaction", response_model=InteractionOut, status_code=201)
def create_interaction(payload: InteractionIn, request: Request, user=Depends(get_current_user)) -> InteractionOut:
    """Create an interaction event for a customer."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into interactions (customer_id, type, channel, content, meta, created_by)
            values (%s, %s, %s, %s, %s::jsonb, %s)
            returning id, customer_id, type, channel, content, meta
            """,
            (payload.customer_id, payload.type, payload.channel, payload.content, json.dumps(payload.meta or {}), user.get("id")),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Insert failed")
        out = InteractionOut(
            id=int(r[0]),
            customer_id=int(r[1]),
            type=r[2],
            channel=r[3],
            content=r[4],
            meta=r[5] or {},
        )
    audit_log("create", "interaction", out.id, {"customer_id": payload.customer_id}, user.get("id"), request.client.host if request.client else None)
    return out


@router.get("", summary="List interactions", response_model=List[InteractionOut])
def list_interactions(
    customer_id: Optional[int] = Query(None, description="Filter by customer ID"),
    user=Depends(get_current_user),
) -> List[InteractionOut]:
    """List interactions, optionally by customer."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        if customer_id is not None:
            cur.execute(
                "select id, customer_id, type, channel, content, meta from interactions where customer_id=%s order by id desc limit 100",
                (customer_id,),
            )
        else:
            cur.execute("select id, customer_id, type, channel, content, meta from interactions order by id desc limit 100")
        rows = cur.fetchall() or []
        return [
            InteractionOut(id=int(r[0]), customer_id=int(r[1]), type=r[2], channel=r[3], content=r[4], meta=r[5] or {})
            for r in rows
        ]
