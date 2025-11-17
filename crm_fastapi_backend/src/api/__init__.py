"""
API package exposing the FastAPI app and routers.
This module allows importing `app` directly from src.api for convenience.
"""

from .main import app

__all__ = ["app"]
