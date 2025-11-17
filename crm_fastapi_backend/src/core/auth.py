from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, status

from src.core.config import get_settings
from src.core.db import get_conn
from src.core.security import PasswordHash, generate_token, hash_password, parse_bearer_token, verify_password


def _ensure_user_tables() -> None:
    """Create users and sessions tables if they do not exist."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists users (
                id bigserial primary key,
                email text not null unique,
                password_algo text not null,
                password_iterations int not null,
                password_salt text not null,
                password_hash text not null,
                role text not null default 'agent',
                created_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            """
            create table if not exists sessions (
                token text primary key,
                user_id bigint not null references users(id) on delete cascade,
                expires_at timestamptz not null,
                revoked boolean not null default false,
                created_at timestamptz not null default now()
            )
            """
        )


def _serialize_ph(ph: PasswordHash) -> Dict[str, Any]:
    return {
        "algo": ph.algo,
        "iterations": ph.iterations,
        "salt_b64": ph.salt_b64,
        "hash_hex": ph.hash_hex,
    }


def _create_user(email: str, password: str, role: str = "agent") -> int:
    _ensure_user_tables()
    ph = hash_password(password)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into users (email, password_algo, password_iterations, password_salt, password_hash, role)
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (email, ph.algo, ph.iterations, ph.salt_b64, ph.hash_hex, role),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Failed to create user")
        return int(row[0])


def _get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    _ensure_user_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, email, password_algo, password_iterations, password_salt, password_hash, role from users where email=%s",
            (email,),
        )
        r = cur.fetchone()
        if not r:
            return None
        return {
            "id": int(r[0]),
            "email": r[1],
            "ph": PasswordHash(algo=r[2], iterations=int(r[3]), salt_b64=r[4], hash_hex=r[5]),
            "role": r[6],
        }


def _get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    _ensure_user_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, email, password_algo, password_iterations, password_salt, password_hash, role from users where id=%s",
            (user_id,),
        )
        r = cur.fetchone()
        if not r:
            return None
        return {
            "id": int(r[0]),
            "email": r[1],
            "ph": PasswordHash(algo=r[2], iterations=int(r[3]), salt_b64=r[4], hash_hex=r[5]),
            "role": r[6],
        }


def _create_session(user_id: int) -> Dict[str, Any]:
    settings = get_settings()
    ttl = dt.timedelta(seconds=settings.token_ttl_seconds)
    token = generate_token()
    expires_at = dt.datetime.now(dt.timezone.utc) + ttl
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into sessions (token, user_id, expires_at) values (%s, %s, %s) returning token, expires_at",
            (token, user_id, expires_at),
        )
        r = cur.fetchone()
        if not r:
            raise RuntimeError("Failed to create session")
        return {"token": r[0], "expires_at": r[1]}


def _revoke_session(token: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("update sessions set revoked=true where token=%s", (token,))


# PUBLIC_INTERFACE
def signup_user(email: str, password: str, role: str = "agent") -> int:
    """Create a new user with the given role; returns user ID."""
    if not email or not password:
        raise ValueError("Email and password are required.")
    return _create_user(email=email.lower().strip(), password=password, role=role)


# PUBLIC_INTERFACE
def login_user(email: str, password: str) -> Dict[str, Any]:
    """Authenticate credentials and create a session; returns token and expiry."""
    user = _get_user_by_email(email.lower().strip())
    if not user or not verify_password(password, user["ph"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return _create_session(user["id"])


# PUBLIC_INTERFACE
def revoke_token(token: str) -> None:
    """Revoke a session token."""
    _revoke_session(token)


# PUBLIC_INTERFACE
def authenticate_token(token: str) -> Dict[str, Any]:
    """Validate a token, returning user info if valid or raising HTTPException."""
    _ensure_user_tables()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select u.id, u.email, u.role, s.expires_at, s.revoked
            from sessions s
            join users u on u.id = s.user_id
            where s.token=%s
            """,
            (token,),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        user_id, email, role, expires_at, revoked = int(r[0]), r[1], r[2], r[3], bool(r[4])
        if revoked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
        if expires_at < dt.datetime.now(dt.timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
        return {"id": user_id, "email": email, "role": role}


# PUBLIC_INTERFACE
def get_current_user(request: Request) -> Dict[str, Any]:
    """Dependency to resolve the current authenticated user from Authorization header."""
    token = parse_bearer_token(request.headers.get("Authorization"))
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return authenticate_token(token)


# PUBLIC_INTERFACE
def require_role(required: str):
    """Dependency factory to enforce a required role on the current user."""

    def _dep(user=Depends(get_current_user)) -> Dict[str, Any]:
        role = user.get("role")
        if role != required:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _dep
