from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from src.core.audit import audit_log
from src.core.auth import get_current_user, login_user, revoke_token, signup_user

router = APIRouter(prefix="/auth", tags=["Auth"])


class SignupIn(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password (min 8 chars)")
    role: str = Field("agent", description="User role (admin/agent)")


class LoginIn(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password (min 8 chars)")


class TokenOut(BaseModel):
    token: str = Field(..., description="Opaque bearer token")
    expires_at: str = Field(..., description="Token expiry timestamp (UTC)")


@router.post("/signup", summary="Create user", response_model=dict)
def signup(payload: SignupIn, request: Request) -> Dict[str, Any]:
    """Create a new user account."""
    try:
        user_id = signup_user(payload.email, payload.password, payload.role)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User creation failed") from e
    audit_log("signup", "user", user_id, {"email": payload.email}, None, request.client.host if request.client else None)
    return {"user_id": user_id}


@router.post("/login", summary="Login", response_model=TokenOut)
def login(payload: LoginIn, request: Request) -> TokenOut:
    """Authenticate and return a bearer token."""
    out = login_user(payload.email, payload.password)
    audit_log("login", "session", None, {"email": payload.email}, None, request.client.host if request.client else None)
    return TokenOut(token=out["token"], expires_at=out["expires_at"].isoformat())


@router.post("/logout", summary="Logout", status_code=204)
def logout(request: Request, user=Depends(get_current_user)) -> None:
    """Revoke the current session token."""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Authorization header")
    token = auth_header.split(" ", 1)[1]
    revoke_token(token)
    audit_log("logout", "session", None, None, user.get("id"), request.client.host if request.client else None)
    return None


@router.get("/me", summary="Who am I", response_model=dict)
def me(user=Depends(get_current_user)) -> Dict[str, Any]:
    """Return the current authenticated user profile."""
    return {"id": user["id"], "email": user["email"], "role": user["role"]}
