from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
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


class CustomerOut(CustomerIn):
    id: int = Field(..., description="Customer ID")


def _ensure_table() -> None:
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


@router.get("", summary="List customers", response_model=List[CustomerOut])
def list_customers(
    q: Optional[str] = Query(None, description="Search text for name/email/phone"),
    user=Depends(get_current_user),
) -> List[CustomerOut]:
    """List customers with optional search."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        if q:
            like = f"%{q.lower()}%"
            cur.execute(
                """
                select id, name, email, phone, data from customers
                where lower(name) like %s or lower(coalesce(email,'')) like %s or lower(coalesce(phone,'')) like %s
                order by id desc limit 100
                """,
                (like, like, like),
            )
        else:
            cur.execute("select id, name, email, phone, data from customers order by id desc limit 100")
        rows = cur.fetchall() or []
        return [
            CustomerOut(id=int(r[0]), name=r[1], email=r[2], phone=r[3], data=r[4] or {})
            for r in rows
        ]


@router.post("", summary="Create customer", response_model=CustomerOut, status_code=201)
def create_customer(payload: CustomerIn, request: Request, user=Depends(get_current_user)) -> CustomerOut:
    """Create a customer record."""
    _ensure_table()
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


@router.get("/{customer_id}", summary="Get customer", response_model=CustomerOut)
def get_customer(customer_id: int, user=Depends(get_current_user)) -> CustomerOut:
    """Get a customer by ID."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select id, name, email, phone, data from customers where id=%s", (customer_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        return CustomerOut(id=int(r[0]), name=r[1], email=r[2], phone=r[3], data=r[4] or {})


@router.put("/{customer_id}", summary="Update customer", response_model=CustomerOut)
def update_customer(customer_id: int, payload: CustomerIn, request: Request, user=Depends(get_current_user)) -> CustomerOut:
    """Update a customer record."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update customers
            set name=%s, email=%s, phone=%s, data=%s::jsonb, updated_at=now()
            where id=%s
            returning id, name, email, phone, data
            """,
            (payload.name, payload.email, payload.phone, json.dumps(payload.data or {}), customer_id),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        out = CustomerOut(id=int(r[0]), name=r[1], email=r[2], phone=r[3], data=r[4] or {})
    audit_log("update", "customer", customer_id, {"fields": list(payload.model_dump().keys())}, user.get("id"), request.client.host if request.client else None)
    return out


@router.delete("/{customer_id}", summary="Delete customer", status_code=204)
async def delete_customer(customer_id: int, request: Request, user=Depends(get_current_user)) -> Response:
    """Delete a customer and return 204 No Content."""
    _ensure_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("delete from customers where id=%s", (customer_id,))
    audit_log("delete", "customer", customer_id, None, user.get("id"), request.client.host if request.client else None)
    return Response(status_code=204)
