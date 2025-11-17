from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.core.auth import get_current_user

router = APIRouter(prefix="/inbox", tags=["Inbox"])


class InboxItem(BaseModel):
    id: str = Field(..., description="Item id")
    type: str = Field(..., description="Type (request/interaction/workflow)")
    title: str = Field(..., description="Item title")
    priority: str = Field(..., description="Priority")
    status: str = Field(..., description="Status")


@router.get("", summary="List inbox items", response_model=List[InboxItem])
def list_inbox(
    only_priority: Optional[str] = Query(None, description="Filter by priority"),
    user=Depends(get_current_user),
) -> List[InboxItem]:
    """Return a minimal stubbed inbox for the current user."""
    items = [
        InboxItem(id="req-101", type="request", title="Follow up with ACME", priority="high", status="open"),
        InboxItem(id="int-52", type="interaction", title="New chat message", priority="normal", status="unread"),
    ]
    if only_priority:
        items = [i for i in items if i.priority == only_priority]
    return items
