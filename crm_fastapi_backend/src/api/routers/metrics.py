from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.core.auth import get_current_user
from src.core.db import get_conn

router = APIRouter(prefix="/metrics", tags=["Metrics"])


class MetricsOut(BaseModel):
    customers: int = Field(..., description="Total customers")
    open_requests: int = Field(..., description="Open requests")
    resolved_requests_last_7d: int = Field(..., description="Requests resolved in the last 7 days")


@router.get("/summary", summary="Metrics summary", response_model=MetricsOut)
def metrics_summary(user=Depends(get_current_user)) -> MetricsOut:
    """Return minimal KPI counts."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("create table if not exists customers (id bigserial primary key)")
        cur.execute(
            """
            create table if not exists requests (
                id bigserial primary key,
                status text not null default 'open',
                updated_at timestamptz not null default now()
            )
            """
        )
        cur.execute("select count(1) from customers")
        customers = int(cur.fetchone()[0])
        cur.execute("select count(1) from requests where status='open'")
        open_requests = int(cur.fetchone()[0])
        cur.execute("select count(1) from requests where status='resolved' and updated_at >= now() - interval '7 days'")
        resolved_last_7d = int(cur.fetchone()[0])
    return MetricsOut(customers=customers, open_requests=open_requests, resolved_requests_last_7d=resolved_last_7d)
