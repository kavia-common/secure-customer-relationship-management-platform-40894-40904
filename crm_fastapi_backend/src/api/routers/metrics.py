from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.core.auth import get_current_user, require_roles
from src.core.db import get_conn

router = APIRouter(prefix="/metrics", tags=["Metrics"])


class MetricsOut(BaseModel):
    customers: int = Field(..., description="Total customers")
    open_requests: int = Field(..., description="Open requests")
    resolved_requests_last_7d: int = Field(..., description="Requests resolved in the last 7 days")


# PUBLIC_INTERFACE
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


class RequestsMetricsOut(BaseModel):
    open: int = 0
    assigned: int = 0
    in_progress: int = 0
    escalated: int = 0
    resolved: int = 0
    closed: int = 0


# PUBLIC_INTERFACE
@router.get("/requests", summary="Requests metrics by status", response_model=RequestsMetricsOut)
def requests_metrics(user=Depends(get_current_user)) -> RequestsMetricsOut:
    """Aggregate requests by status."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select status, count(1) from requests group by status"
        )
        rows = cur.fetchall() or []
        data = {r[0]: int(r[1]) for r in rows}
        return RequestsMetricsOut(
            open=data.get("open", 0),
            assigned=data.get("assigned", 0),
            in_progress=data.get("in_progress", 0),
            escalated=data.get("escalated", 0),
            resolved=data.get("resolved", 0),
            closed=data.get("closed", 0),
        )


class AgentMetric(BaseModel):
    user_id: int
    email: str
    open_assigned: int


# PUBLIC_INTERFACE
@router.get("/agents", summary="Agent workload metrics", response_model=List[AgentMetric], dependencies=[Depends(require_roles(["admin", "supervisor"]))])
def agents_metrics() -> List[AgentMetric]:
    """List agents with count of open/assigned requests."""
    with get_conn() as conn, conn.cursor() as cur:
        # Ensure tables exist
        cur.execute("create table if not exists users (id bigserial primary key, email text unique not null, role text not null default 'agent', password_algo text not null, password_iterations int not null, password_salt text not null, password_hash text not null)")
        cur.execute("create table if not exists requests (id bigserial primary key, assignee_id bigint null, status text not null default 'open')")
        cur.execute(
            """
            select u.id, u.email, coalesce(r.cnt,0) as open_assigned
            from users u
            left join (
                select assignee_id, count(1) as cnt
                from requests
                where assignee_id is not null and status in ('open','assigned','in_progress','escalated')
                group by assignee_id
            ) r on r.assignee_id = u.id
            where u.role in ('agent','supervisor')
            order by open_assigned desc, u.id
            """
        )
        rows = cur.fetchall() or []
        return [AgentMetric(user_id=int(r[0]), email=r[1], open_assigned=int(r[2])) for r in rows]
