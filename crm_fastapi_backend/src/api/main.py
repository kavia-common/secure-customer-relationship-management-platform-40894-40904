from __future__ import annotations

import logging
import os
import time
from typing import Callable

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.api.routers import admin, auth, customers, inbox, interactions, metrics, requests as reqs, workflows
from src.api.routers import users
from src.core.config import get_settings
from src.core.db import close_pool, init_pool, get_conn
from src.core.migrations import apply_migrations_from_path

logger = logging.getLogger("crm_backend.api.main")
logging.basicConfig(level=logging.INFO)

settings = get_settings()

openapi_tags = [
    {"name": "Auth", "description": "Authentication and session management"},
    {"name": "Customers", "description": "Customer 360 operations"},
    {"name": "Interactions", "description": "Omni-channel interactions"},
    {"name": "Requests", "description": "Service/complaint requests and lifecycle"},
    {"name": "Workflows", "description": "Workflow automation stubs"},
    {"name": "Inbox", "description": "Agent inbox"},
    {"name": "Metrics", "description": "KPIs and dashboard metrics"},
    {"name": "Admin", "description": "User/role management and audit"},
    {"name": "Health", "description": "Liveness, readiness, and migration status"},
]

app = FastAPI(
    title=settings.app_name,
    description="Secure CRM backend API",
    version=settings.app_version,
    openapi_tags=openapi_tags,
)

# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # Minimal CSP: allow same-origin and inline styles for docs; adjust per deployment
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
        return response


# Simple in-memory per-IP throttling (excluding health endpoints)
class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, exclude_paths: tuple[str, ...] = ("/", "/health/db", "/health/migrations")):
        super().__init__(app)
        self.window = settings.rate_limit_window_seconds
        self.limit = settings.rate_limit_requests
        self.exclude_paths = set(exclude_paths)
        self.state: dict[str, tuple[int, float]] = {}  # ip -> (count, reset_ts)

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path if request.url else ""
        if path in self.exclude_paths:
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.time()
        count, reset = self.state.get(ip, (0, now + self.window))
        if now > reset:
            count, reset = 0, now + self.window
        count += 1
        self.state[ip] = (count, reset)
        if count > self.limit:
            retry = max(1, int(reset - now))
            headers = {"Retry-After": str(retry)}
            # Ensure security headers are present on throttled responses
            headers.update({
                "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'",
            })
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429, headers=headers)
        return await call_next(request)


# Middleware registration order:
# - RateLimiter first
# - Security headers next
# - CORS last so it applies to all responses including errors/preflight
app.add_middleware(RateLimiterMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    """Initialize DB pool and run migrations (if configured)."""
    # Log effective configuration at boot to aid diagnostics
    logger.info(
        "Boot configuration: BACKEND_PORT=%s, CORS_ALLOW_ORIGINS=%s, DATABASE_URL set=%s, MIGRATIONS_PATH=%s",
        settings.backend_port,
        settings.cors_origins,
        bool(settings.database_url),
        settings.migrations_path or "<none>",
    )
    try:
        init_pool()
        if not settings.database_url:
            logger.warning("DATABASE_URL not set; running in degraded mode (DB-backed endpoints will error).")
        if settings.migrations_path:
            applied = apply_migrations_from_path(settings.migrations_path)
            if applied:
                logger.info("Applied migrations: %s", ", ".join(applied))
    except Exception as e:
        # Avoid crashing on startup if DB is not available; run in degraded mode and log
        logger.warning("Startup degraded: database not available or migration failed: %s", e)


@app.on_event("shutdown")
def on_shutdown() -> None:
    """Gracefully close DB pool."""
    try:
        close_pool()
    except Exception:
        # Best-effort cleanup
        pass


# PUBLIC_INTERFACE
@app.get(
    "/",
    summary="Health Check",
    tags=["Health"],
)
def health_check():
    """Simple liveness check."""
    return {"status": "ok"}


# PUBLIC_INTERFACE
@app.get(
    "/health/db",
    summary="Database health",
    tags=["Health"],
)
def health_db():
    """Attempt a simple DB query to verify connectivity and basic readiness.

    Returns:
        200: {"status": "ok"} when DB is reachable
        503: {"status": "degraded", "detail": "..."} when unavailable
    """
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("select 1")
            cur.fetchone()
        return {"status": "ok"}
    except Exception as e:
        # Log sanitized error; avoid sensitive details in the response
        logger.warning("Database health check failed: %s", e)
        return JSONResponse(status_code=503, content={"status": "degraded", "detail": "database unavailable"})


# PUBLIC_INTERFACE
@app.get(
    "/health/migrations",
    summary="Migration status",
    tags=["Health"],
)
def health_migrations():
    """Report migration tracking status and pending count if MIGRATIONS_PATH is configured.

    Returns:
        200: {"status":"ok","applied":<int>,"pending":<int|None>,"latest":{"id":<str>,"applied_at":<iso str>}?}
        503: {"status":"degraded","detail":"..."} when tracking is missing/unreachable
    """
    try:
        applied_count = 0
        latest_id = None
        latest_applied_at_iso = None
        table_used = None

        with get_conn() as conn, conn.cursor() as cur:
            # Prefer schema_migrations (used by this app); fall back to app_migrations if present
            cur.execute("select to_regclass('public.schema_migrations') is not null")
            has_schema = bool(cur.fetchone()[0])

            if has_schema:
                table_used = "schema_migrations"
                cur.execute("select count(1) from schema_migrations")
                applied_count = int(cur.fetchone()[0] or 0)
                cur.execute("select filename, applied_at from schema_migrations order by applied_at desc limit 1")
                r = cur.fetchone()
                if r:
                    latest_id = str(r[0])
                    latest_applied_at_iso = r[1].isoformat() if r[1] is not None else None
            else:
                # Check alternate table name
                cur.execute("select to_regclass('public.app_migrations') is not null")
                has_app = bool(cur.fetchone()[0])
                if has_app:
                    table_used = "app_migrations"
                    cur.execute("select count(1) from app_migrations")
                    applied_count = int(cur.fetchone()[0] or 0)
                    # Attempt to read an id/timestamp if available
                    try:
                        cur.execute("select id, applied_at from app_migrations order by applied_at desc limit 1")
                        r2 = cur.fetchone()
                        if r2:
                            latest_id = str(r2[0])
                            latest_applied_at_iso = r2[1].isoformat() if r2[1] is not None else None
                    except Exception:
                        # app_migrations schema may differ; ignore latest if not available
                        pass

        # Determine pending migrations based on MIGRATIONS_PATH (if configured)
        pending = None
        if settings.migrations_path and os.path.isdir(settings.migrations_path):
            sql_files = [f for f in os.listdir(settings.migrations_path) if f.lower().endswith(".sql")]
            if table_used:
                pending = max(0, len(sql_files) - applied_count)
            else:
                # If tracking table is missing, all files are considered pending
                pending = len(sql_files)

        if table_used is None:
            # Tracking table missing/unavailable
            return JSONResponse(status_code=503, content={"status": "degraded", "detail": "migration tracking table missing"})

        payload = {"status": "ok", "applied": applied_count, "pending": pending}
        if latest_id or latest_applied_at_iso:
            payload["latest"] = {"id": latest_id, "applied_at": latest_applied_at_iso}
        return payload
    except Exception as e:
        # Log sanitized error; avoid sensitive details in the response
        logger.warning("Health migrations check failed: %s", e)
        return JSONResponse(status_code=503, content={"status": "degraded", "detail": "migration tracking unavailable"})


# Register routers
app.include_router(auth.router)
app.include_router(customers.router)
app.include_router(interactions.router)
app.include_router(reqs.router)
app.include_router(workflows.router)
app.include_router(inbox.router)
app.include_router(metrics.router)
app.include_router(admin.router)
app.include_router(users.router)


# PUBLIC_INTERFACE
def run_server() -> None:
    """Run the Uvicorn server binding to 0.0.0.0 and BACKEND_PORT (default 3001)."""
    host = "0.0.0.0"
    port = int(settings.backend_port)
    logger.info("Starting server on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
