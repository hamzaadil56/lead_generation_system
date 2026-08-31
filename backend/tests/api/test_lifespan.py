"""The app's lifespan is what actually starts the scheduler in production.

Nothing else in the suite exercises it: the only app the other API tests
build passes `disable_scheduler=True`, so deleting `scheduler.start()` --
or the `lifespan=lifespan` argument entirely -- would leave the suite green
while the deployed system executed nothing, forever. These two tests are
the only place the enabled path runs.

Safety: every job callable is replaced with a recording stub *before* the
lifespan builds the scheduler, and `live_providers` is replaced with a
tripwire that raises. A real scheduler thread does start, but every job it
could fire is a stub -- no provider is constructed, no HTTP client exists,
and no run is claimed or executed. (In practice nothing fires at all: the
poller's first run is 30 seconds out and the rest are hours away.)
"""
import os

os.environ.setdefault("DATABASE_URL",
                      "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test")
os.environ.setdefault("SERPER_KEY", "test-serper-key")
os.environ.setdefault("FIRECRAWL_KEY", "test-firecrawl-key")

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app

# `reset_stuck_runs` is intentionally absent: it is called once at startup,
# never on a timer (a timed reconciler requeues live runs mid-flight).
JOB_IDS = {"poll_queued_runs", "retry_failed_businesses",
           "refresh_stale_businesses"}


@pytest.fixture
def stubbed(monkeypatch):
    """Stub the boundary so a started scheduler cannot reach anything real."""
    import app.scheduler as sched
    import app.services.run_executor as run_executor

    calls: dict[str, list[Any]] = {"reset": [], "built": []}

    def fake_reset(max_age_hours: int = 1) -> int:
        calls["reset"].append(max_age_hours)
        return 0

    # `build_scheduler` resolves these as module globals when it runs, so
    # the stubs -- not the real jobs -- are what get registered.
    monkeypatch.setattr(sched, "reset_stuck_runs", fake_reset)
    monkeypatch.setattr(sched, "poll_queued_runs", lambda: None)
    monkeypatch.setattr(sched, "retry_failed_businesses",
                        lambda max_attempts=3: 0)
    monkeypatch.setattr(sched, "refresh_stale_businesses",
                        lambda older_than_days=90: 0)

    def no_providers() -> None:
        raise AssertionError(
            "the lifespan test constructed real, paid providers")

    monkeypatch.setattr(run_executor, "live_providers", no_providers)

    real_build = sched.build_scheduler

    def spy_build():
        scheduler = real_build()
        calls["built"].append(scheduler)
        return scheduler

    monkeypatch.setattr(sched, "build_scheduler", spy_build)
    return calls


def test_the_lifespan_starts_the_scheduler_and_shuts_it_down(stubbed):
    app = create_app()
    assert app.state.disable_scheduler is False

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert len(stubbed["built"]) == 1, "the lifespan never built a scheduler"
        scheduler = stubbed["built"][0]
        assert scheduler.running, "the lifespan never started the scheduler"
        assert {j.id for j in scheduler.get_jobs()} == JOB_IDS

    assert not scheduler.running, "the lifespan never shut the scheduler down"
    # Startup passes a cutoff of 0: a freshly started process owns no
    # in-flight runs, so anything still `running` is orphaned.
    assert stubbed["reset"] == [0]


def test_disable_scheduler_leaves_the_lifespan_inert(stubbed):
    """The switch the whole test suite depends on."""
    with TestClient(create_app(disable_scheduler=True)) as client:
        assert client.get("/health").status_code == 200

    assert stubbed["built"] == []
    assert stubbed["reset"] == []
