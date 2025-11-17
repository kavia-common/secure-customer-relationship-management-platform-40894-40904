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


# PUBLIC_INTERFACE
@router.get("", summary="List inbox items (deprecated)", response_model=List[InboxItem])
def list_inbox(
    only_priority: Optional[str] = Query(None, description="Filter by priority"),
    user=Depends(get_current_user),
) -> List[InboxItem]:
    """Return a minimal stubbed inbox for the current user. Deprecated in favor of /inbox/messages."""
    items = [
        InboxItem(id="req-101", type="request", title="Follow up with ACME", priority="high", status="open"),
        InboxItem(id="int-52", type="interaction", title="New chat message", priority="normal", status="unread"),
    ]
    if only_priority:
        items = [i for i in items if i.priority == only_priority]
    return items


# PUBLIC_INTERFACE
@router.get("/messages", summary="List inbox messages", response_model=List[InboxItem])
def list_messages(
    priority: Optional[str] = Query(None, description="Filter by priority"),
    user=Depends(get_current_user),
) -> List[InboxItem]:
    """Stubbed inbox messages list."""
    return list_inbox(priority, user)  # reuse stub


# PUBLIC_INTERFACE
@router.get("/messages/{message_id}", summary="Get inbox message", response_model=InboxItem)
def get_message(message_id: str, user=Depends(get_current_user)) -> InboxItem:
    """Stubbed inbox message by id."""
    # Just echo a fake item
    return InboxItem(id=message_id, type="request", title="Stub message", priority="normal", status="open")


# PUBLIC_INTERFACE
@router.post("/messages", summary="Create inbox message", response_model=InboxItem, status_code=201)
def create_message(item: InboxItem, user=Depends(get_current_user)) -> InboxItem:
    """Stubbed create message (echoes back)."""
    return item
