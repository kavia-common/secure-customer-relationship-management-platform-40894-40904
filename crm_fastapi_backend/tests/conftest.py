import os
import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture(scope="session")
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture(scope="session")
def has_database() -> bool:
    """Whether DATABASE_URL is configured for integration tests."""
    return bool(os.getenv("DATABASE_URL"))
