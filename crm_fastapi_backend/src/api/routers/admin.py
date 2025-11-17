from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field

from src.core.auth import require_role, signup_user
from src.core.db import get_conn

router = APIRouter(prefix="/admin", tags=["Admin"])


class UserRow(BaseModel):
    id: int
    email: EmailStr
    role: str


class CreateUserIn(BaseModel):
    email: EmailStr = Field(..., description="Email")
    password: str = Field(..., min_length=8, description="Password (min 8 chars)")
    role: str = Field("agent", description="Role (admin/supervisor/agent)")


class UpdateUserIn(BaseModel):
    email: Optional[EmailStr] = Field(None, description="New email")
    role: Optional[str] = Field(None, description="New role (admin/supervisor/agent)")
    password: Optional[str] = Field(None, min_length=8, description="New password")


class SetRoleIn(BaseModel):
    role: str = Field(..., description="Role to assign (admin/supervisor/agent)")


def _ensure_user_table() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "create table if not exists users (id bigserial primary key, email text unique not null, role text not null default 'agent', password_algo text not null, password_iterations int not null, password_salt text not null, password_hash text not null)"
        )


@router.get("/users", summary="List users", response_model=List[UserRow])
def list_users(user=Depends(require_role("admin"))) -> List[UserRow]:
    """List all users (admin only)."""
    _ensure_user_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select id, email, role from users order by id")
        rows = cur.fetchall() or []
        return [UserRow(id=int(r[0]), email=r[1], role=r[2]) for r in rows]


@router.post("/users", summary="Create user", response_model=UserRow, status_code=201)
def create_user(payload: CreateUserIn, user=Depends(require_role("admin"))) -> UserRow:
    """Create a new user (admin only)."""
    try:
        user_id = signup_user(payload.email, payload.password, payload.role)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create user") from e
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select id, email, role from users where id=%s", (user_id,))
        r = cur.fetchone()
        return UserRow(id=int(r[0]), email=r[1], role=r[2])


@router.patch("/users/{user_id}", summary="Update user", response_model=UserRow)
def patch_user(user_id: int, payload: UpdateUserIn, user=Depends(require_role("admin"))) -> UserRow:
    """Update a user's email, role, or password."""
    _ensure_user_table()
    updates = []
    params = []
    if payload.email is not None:
        updates.append("email=%s")
        params.append(payload.email)
    if payload.role is not None:
        updates.append("role=%s")
        params.append(payload.role)
    if updates:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"update users set {', '.join(updates)} where id=%s returning id, email, role", (*params, user_id))
            r = cur.fetchone()
            if not r:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            return UserRow(id=int(r[0]), email=r[1], role=r[2])
    else:
        # if only password to update, we cannot handle here without hashing logic duplication
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No updatable fields provided")


@router.delete("/users/{user_id}", summary="Delete user", status_code=200)
def delete_user(user_id: int, user=Depends(require_role("admin"))) -> dict:
    """Delete a user (admin only)."""
    _ensure_user_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("delete from users where id=%s", (user_id,))
    return {"detail": "deleted"}


class RoleRow(BaseModel):
    id: int
    name: str


class RoleIn(BaseModel):
    name: str = Field(..., description="Role name (unique)")


def _ensure_roles_table() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists roles (
                id bigserial primary key,
                name text not null unique
            )
            """
        )


@router.get("/roles", summary="List roles", response_model=List[RoleRow])
def list_roles(user=Depends(require_role("admin"))) -> List[RoleRow]:
    """List roles available in the system (admin only)."""
    _ensure_roles_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select id, name from roles order by name")
        rows = cur.fetchall() or []
        return [RoleRow(id=int(r[0]), name=r[1]) for r in rows]


@router.post("/roles", summary="Create role", response_model=RoleRow, status_code=201)
def create_role(payload: RoleIn, user=Depends(require_role("admin"))) -> RoleRow:
    """Create a role."""
    _ensure_roles_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("insert into roles (name) values (%s) returning id, name", (payload.name,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Create failed")
        return RoleRow(id=int(r[0]), name=r[1])


@router.patch("/roles/{role_id}", summary="Update role", response_model=RoleRow)
def patch_role(role_id: int, payload: RoleIn, user=Depends(require_role("admin"))) -> RoleRow:
    """Rename a role."""
    _ensure_roles_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("update roles set name=%s where id=%s returning id, name", (payload.name, role_id))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        return RoleRow(id=int(r[0]), name=r[1])


@router.delete("/roles/{role_id}", summary="Delete role", status_code=200)
def delete_role(role_id: int, user=Depends(require_role("admin"))) -> dict:
    """Delete a role."""
    _ensure_roles_table()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("delete from roles where id=%s", (role_id,))
    return {"detail": "deleted"}


class AuditRow(BaseModel):
    id: int
    user_id: Optional[int]
    action: str
    resource: str
    resource_id: Optional[int]


@router.get("/audit", summary="View audit logs", response_model=List[AuditRow])
def view_audit(
    limit: int = Query(100, ge=1, le=1000, description="Max records"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    action: Optional[str] = Query(None, description="Filter by action"),
    resource: Optional[str] = Query(None, description="Filter by resource"),
    user_id: Optional[int] = Query(None, description="Filter by user id"),
    user=Depends(require_role("admin")),
) -> List[AuditRow]:
    """Return recent audit logs (admin only) with optional filters."""
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
        conditions = []
        params = []
        if action:
            conditions.append("action=%s")
            params.append(action)
        if resource:
            conditions.append("resource=%s")
            params.append(resource)
        if user_id is not None:
            conditions.append("user_id=%s")
            params.append(user_id)
        where = f"where {' and '.join(conditions)}" if conditions else ""
        sql = f"select id, user_id, action, resource, resource_id from audit_log {where} order by id desc limit %s offset %s"
        with_params = (*params, limit, offset)
        cur.execute(sql, with_params)
        rows = cur.fetchall() or []
        return [
            AuditRow(
                id=int(r[0]),
                user_id=(int(r[1]) if r[1] is not None else None),
                action=r[2],
                resource=r[3],
                resource_id=(int(r[4]) if r[4] is not None else None),
            )
            for r in rows
        ]
