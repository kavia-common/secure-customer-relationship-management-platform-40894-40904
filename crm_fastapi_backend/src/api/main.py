from __future__ import annotations

import time
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.api.routers import admin, auth, customers, inbox, interactions, metrics, requests as reqs, workflows
from src.core.config import get_settings
from src.core.db import close_pool, init_pool
from src.core.migrations import apply_migrations_from_path

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


# Simple in-memory per-IP throttling
class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI):
        super().__init__(app)
        self.window = settings.rate_limit_window_seconds
        self.limit = settings.rate_limit_requests
        self.state: dict[str, tuple[int, float]] = {}  # ip -> (count, reset_ts)

    async def dispatch(self, request: Request, call_next: Callable):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        count, reset = self.state.get(ip, (0, now + self.window))
        if now > reset:
            count, reset = 0, now + self.window
        count += 1
        self.state[ip] = (count, reset)
        if count > self.limit:
            retry = max(1, int(reset - now))
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429, headers={"Retry-After": str(retry)})
        return await call_next(request)


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimiterMiddleware)


@app.on_event("startup")
def on_startup() -> None:
    """Initialize DB pool and run migrations (if configured)."""
    try:
        init_pool()
        if settings.migrations_path:
            apply_migrations_from_path(settings.migrations_path)
    except Exception:
        # Avoid crashing docs generation on import; runtime logs should capture actual failure
        pass


@app.on_event("shutdown")
def on_shutdown() -> None:
    """Gracefully close DB pool."""
    try:
        close_pool()
    except Exception:
        pass


@app.get(
    "/",
    summary="Health Check",
    tags=["Metrics"],
)
def health_check():
    """Simple liveness check."""
    return {"status": "ok"}


# Register routers
app.include_router(auth.router)
app.include_router(customers.router)
app.include_router(interactions.router)
app.include_router(reqs.router)
app.include_router(workflows.router)
app.include_router(inbox.router)
app.include_router(metrics.router)
app.include_router(admin.router)
