"""Isolated test database fixtures.

These tests must never truncate or write to the database configured for a running
OSAP environment. Every test gets a private in-memory SQLite engine.
"""

import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Make even module-level application initialization use a throwaway database.
# Individual tests then override get_db with their own in-memory engine.
os.environ["AI_PUBLICIDAD_ENV"] = "test"
os.environ["AI_PUBLICIDAD_DATABASE_URL"] = "sqlite://"

from api.main import app  # noqa: E402  # config environment must be set before app import
from domain.models import Base
from infrastructure.database import get_db


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(test_engine, monkeypatch):
    def override_get_db():
        with Session(test_engine) as db:
            yield db

    # The normal unit/integration tests use a deliberate non-production auth
    # context; no request is made against the configured OSAP database.
    monkeypatch.setattr(
        "application.security.get_settings",
        lambda: SimpleNamespace(env="test", service_token=""),
    )
    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()
