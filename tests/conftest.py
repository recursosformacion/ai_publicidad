"""Isolated test database fixtures.

These tests must never truncate or write to the database configured for a running
OSAP environment. Every test gets a private in-memory SQLite engine.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from types import SimpleNamespace

from api.main import app
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
