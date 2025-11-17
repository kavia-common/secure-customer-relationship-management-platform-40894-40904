from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from src.core.auth import require_role
from src.core.db import get_conn

router = APIRouter(prefix="/admin", tags=["Admin"])


class UserRow(BaseModel):
    id: int
    email: EmailStr
    role: str


class SetRoleIn(BaseModel):
    role: str = Field(..., description="Role to assign (admin/agent)")


@router.get("/users", summary="List users", response_model=List[UserRow])
def list_users(user=Depends(require_role("admin"))) -> List[UserRow]:
    """List all users (admin only)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "create table if not exists users (id bigserial primary key, email text unique not null, role text not null default 'agent', password_algo text not null, password_iterations int not null, password_salt text not null, password_hash text not null)"
        )
        cur.execute("select id, email, role from users order by id")
        rows = cur.fetchall() or []
        return [UserRow(id=int(r[0]), email=r[1], role=r[2]) for r in rows]


@router.put("/users/{user_id}/role", summary="Set user role", response_model=UserRow)
def set_role(user_id: int, payload: SetRoleIn, user=Depends(require_role("admin"))) -> UserRow:
    """Set a user's role (admin only)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("update users set role=%s where id=%s returning id, email, role", (payload.role, user_id))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return UserRow(id=int(r[0]), email=r[1], role=r[2])


class AuditRow(BaseModel):
    id: int
    user_id: Optional[int]
    action: str
    resource: str
    resource_id: Optional[int]


@router.get("/audit", summary="View audit logs", response_model=List[AuditRow])
def view_audit(user=Depends(require_role("admin"))) -> List[AuditRow]:
    """Return recent audit logs (admin only)."""
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
        cur.execute("select id, user_id, action, resource, resource_id from audit_log order by id desc limit 200")
        rows = cur.fetchall() or []
        return [
            AuditRow(id=int(r[0]), user_id=(int(r[1]) if r[1] is not None else None), action=r[2], resource=r[3], resource_id=(int(r[4]) if r[4] is not None else None))
            for r in rows
        ]
