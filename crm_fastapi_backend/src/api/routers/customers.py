from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field

from src.core.audit import audit_log
from src.core.auth import get_current_user
from src.core.db import get_conn

router = APIRouter(prefix="/customers", tags=["Customers"])


class CustomerIn(BaseModel):
    name: str = Field(..., description="Full name")
    email: Optional[EmailStr] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    data: Optional[dict] = Field(default_factory=dict, description="Additional attributes")


class CustomerPatch(BaseModel):
    name: Optional[str] = Field(None, description="Full name")
    email: Optional[EmailStr] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    data: Optional[dict] = Field(None, description="Additional attributes")


class CustomerOut(CustomerIn):
    id: int = Field(..., description="Customer ID")


class InteractionSummary(BaseModel):
    id: int
    type: str
    channel: str
    content: str


class RequestSummary(BaseModel):
    id: int
    subject: str
    status: str
    priority: str


class CustomerDetailOut(CustomerOut):
    interactions: List[InteractionSummary] = Field(default_factory=list, description="Recent interactions")
    open_requests: List[RequestSummary] = Field(default_factory=list, description="Open requests")


def _ensure_tables() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists customers (
                id bigserial primary key,
                name text not null,
                email text null,
                phone text null,
                data jsonb not null default '{}'::jsonb,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now()
            )
            """
        )
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


@router.get("", summary="List customers", response_model=List[CustomerOut])
def list_customers(
    q: Optional[str] = Query(None, description="Search text for name/email/phone"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Page size"),
    user=Depends(get_current_user),
) -> List[CustomerOut]:
    """List customers with optional search and pagination."""
    _ensure_tables()
    offset = (page - 1) * page_size
    with get_conn() as conn, conn.cursor() as cur:
        if q:
            like = f"%{q.lower()}%"
            cur.execute(
                """
                select id, name, email, phone, data from customers
                where lower(name) like %s or lower(coalesce(email,'')) like %s or lower(coalesce(phone,'')) like %s
                order by id desc limit %s offset %s
                """,
                (like, like, like, page_size, offset),
            )
        else:
            cur.execute("select id, name, email, phone, data from customers order by id desc limit %s offset %s", (page_size, offset))
        rows = cur.fetchall() or []
        return [
            CustomerOut(id=int(r[0]), name=r[1], email=r[2], phone=r[3], data=r[4] or {})
            for r in rows
        ]


@router.post("", summary="Create customer", response_model=CustomerOut, status_code=201)
def create_customer(payload: CustomerIn, request: Request, user=Depends(get_current_user)) -> CustomerOut:
    """Create a customer record."""
    _ensure_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into customers (name, email, phone, data)
            values (%s, %s, %s, %s::jsonb)
            returning id, name, email, phone, data
            """,
            (payload.name, payload.email, payload.phone, json.dumps(payload.data or {})),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Insert failed")
        out = CustomerOut(id=int(r[0]), name=r[1], email=r[2], phone=r[3], data=r[4] or {})
    audit_log("create", "customer", out.id, {"name": payload.name}, user.get("id"), request.client.host if request.client else None)
    return out


@router.get("/{customer_id}", summary="Get customer", response_model=CustomerDetailOut)
def get_customer(customer_id: int, user=Depends(get_current_user)) -> CustomerDetailOut:
    """Get a customer by ID; include recent interactions and open requests."""
    _ensure_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select id, name, email, phone, data from customers where id=%s", (customer_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        base = CustomerOut(id=int(r[0]), name=r[1], email=r[2], phone=r[3], data=r[4] or {})
        # interactions
        cur.execute(
            "select id, type, channel, content from interactions where customer_id=%s order by id desc limit 20",
            (customer_id,),
        )
        ints = [InteractionSummary(id=int(ir[0]), type=ir[1], channel=ir[2], content=ir[3]) for ir in (cur.fetchall() or [])]
        # open requests
        cur.execute(
            "select id, subject, status, priority from requests where customer_id=%s and status in ('open','in_progress','assigned','escalated') order by id desc",
            (customer_id,),
        )
        reqs = [RequestSummary(id=int(rr[0]), subject=rr[1], status=rr[2], priority=rr[3]) for rr in (cur.fetchall() or [])]
        return CustomerDetailOut(**base.model_dump(), interactions=ints, open_requests=reqs)


@router.patch("/{customer_id}", summary="Patch customer", response_model=CustomerOut)
def patch_customer(customer_id: int, payload: CustomerPatch, request: Request, user=Depends(get_current_user)) -> CustomerOut:
    """Patch a customer record (partial update)."""
    _ensure_tables()
    updates = []
    params = []
    if payload.name is not None:
        updates.append("name=%s")
        params.append(payload.name)
    if payload.email is not None:
        updates.append("email=%s")
        params.append(payload.email)
    if payload.phone is not None:
        updates.append("phone=%s")
        params.append(payload.phone)
    if payload.data is not None:
        updates.append("data=%s::jsonb")
        params.append(json.dumps(payload.data))
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No changes provided")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"update customers set {', '.join(updates)}, updated_at=now() where id=%s returning id, name, email, phone, data",
            (*params, customer_id),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        out = CustomerOut(id=int(r[0]), name=r[1], email=r[2], phone=r[3], data=r[4] or {})
    audit_log("update", "customer", customer_id, {"fields": list(payload.model_dump(exclude_none=True).keys())}, user.get("id"), request.client.host if request.client else None)
    return out


@router.delete("/{customer_id}", summary="Delete customer", status_code=200)
async def delete_customer(customer_id: int, request: Request, user=Depends(get_current_user)) -> dict:
    """Delete a customer and return a small confirmation JSON with HTTP 200."""
    _ensure_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("delete from customers where id=%s", (customer_id,))
    audit_log("delete", "customer", customer_id, None, user.get("id"), request.client.host if request.client else None)
    return {"detail": "deleted"}


@router.get("/{customer_id}/interactions", summary="List customer interactions", response_model=List[InteractionSummary])
def customer_interactions(customer_id: int, user=Depends(get_current_user)) -> List[InteractionSummary]:
    """List interactions for a specific customer."""
    _ensure_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select id, type, channel, content from interactions where customer_id=%s order by id desc limit 100", (customer_id,))
        rows = cur.fetchall() or []
        return [InteractionSummary(id=int(r[0]), type=r[1], channel=r[2], content=r[3]) for r in rows]
