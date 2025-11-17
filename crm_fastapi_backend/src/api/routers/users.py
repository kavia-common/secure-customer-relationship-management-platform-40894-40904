from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.core.auth import get_current_user

router = APIRouter(prefix="/users", tags=["Auth"])


class MeOut(BaseModel):
    """Current user profile response."""
    id: int = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    role: str = Field(..., description="User role")


@router.get("/me", summary="Who am I (users)", response_model=MeOut)
def users_me(user=Depends(get_current_user)) -> Dict[str, Any]:
    """Return the current authenticated user profile (alias endpoint)."""
    return {"id": user["id"], "email": user["email"], "role": user["role"]}
