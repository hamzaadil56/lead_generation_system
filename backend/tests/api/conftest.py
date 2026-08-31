import os

# `app.core.db` builds a SQLAlchemy Engine at import time from
# `Settings.database_url` (via `app.api.deps` -> `app.core.db`), so a
# syntactically valid URL must exist in the environment before
# `app.api.app` is imported below -- regardless of test collection order.
# Mirrors the same guard in tests/integration/test_cli.py.
os.environ.setdefault("DATABASE_URL",
                      "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test")
os.environ.setdefault("SERPER_KEY", "test-serper-key")
os.environ.setdefault("FIRECRAWL_KEY", "test-firecrawl-key")

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.deps import get_db

API_KEY = "test-key-do-not-use-in-prod"


@pytest.fixture
def client(session, monkeypatch):
    """A TestClient wired to the rolled-back test session.

    `get_db` is overridden rather than patched so every router shares the
    one transaction the `session` fixture rolls back after each test.
    """
    monkeypatch.setenv("API_KEY", API_KEY)
    from app.core.config import get_settings
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": API_KEY})
        yield c
    get_settings.cache_clear()


@pytest.fixture
def anon_client(client):
    """Same app, no API key header."""
    client.headers.pop("X-API-Key", None)
    return client
