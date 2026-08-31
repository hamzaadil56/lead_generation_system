"""The four scheduler jobs (ADR-010, spec section 8).

The property every one of these tests defends is that a job never raises
into the APScheduler worker thread: an unhandled exception there removes
the job for the remaining life of the process and nothing says so.
"""
import os

# `app.scheduler` imports `app.core.db`, which builds a SQLAlchemy Engine
# at import time from `Settings.database_url`, so a syntactically valid
# (but never-connected-to, since `get_session` is patched below) URL must
# exist in the environment before the module is imported. Mirrors the same
# guard in tests/api/conftest.py and tests/unit/test_run_executor.py.
os.environ.setdefault("DATABASE_URL",
                      "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test")
os.environ.setdefault("SERPER_KEY", "test-serper-key")
os.environ.setdefault("FIRECRAWL_KEY", "test-firecrawl-key")

from datetime import datetime, timedelta

import pytest

from app.models.business import Business, BusinessStatus
from app.models.run import Run


@pytest.fixture
def patched(monkeypatch, session):
    """Point every job at the rolled-back test session."""
    from contextlib import contextmanager
    import app.scheduler as sched

    @contextmanager
    def factory():
        yield session

    monkeypatch.setattr(sched, "get_session", factory)
    return sched


def test_reset_stuck_runs_requeues_a_run_running_too_long(patched, session):
    session.add(Run(status="running", source="ui", search_plan={},
                    started_at=datetime.utcnow() - timedelta(hours=5)))
    session.commit()

    assert patched.reset_stuck_runs(max_age_hours=1) == 1
    session.expire_all()
    assert session.query(Run).one().status == "queued"


def test_reset_stuck_runs_leaves_a_fresh_run_alone(patched, session):
    session.add(Run(status="running", source="ui", search_plan={},
                    started_at=datetime.utcnow() - timedelta(minutes=5)))
    session.commit()

    assert patched.reset_stuck_runs(max_age_hours=1) == 0
    session.expire_all()
    assert session.query(Run).one().status == "running"


def test_retry_failed_businesses_resets_them_under_the_cap(patched, session):
    session.add(Business(cid="c1", name="Failed Air",
                         status=BusinessStatus.FAILED, attempt_count=1))
    session.commit()

    assert patched.retry_failed_businesses(max_attempts=3) == 1
    session.expire_all()
    assert session.query(Business).one().status == BusinessStatus.DISCOVERED


def test_retry_failed_businesses_gives_up_at_the_cap(patched, session):
    """Without a cap, a permanently broken row is retried forever, and every
    retry that reaches a provider costs money."""
    session.add(Business(cid="c1", name="Hopeless Air",
                         status=BusinessStatus.FAILED, attempt_count=3))
    session.commit()

    assert patched.retry_failed_businesses(max_attempts=3) == 0
    session.expire_all()
    assert session.query(Business).one().status == BusinessStatus.FAILED


def test_refresh_stale_businesses_only_touches_old_rows(patched, session):
    session.add(Business(cid="old", name="Old Air", status=BusinessStatus.SCORED,
                         updated_at=datetime.utcnow() - timedelta(days=200)))
    session.add(Business(cid="new", name="New Air", status=BusinessStatus.SCORED,
                         updated_at=datetime.utcnow()))
    session.commit()

    assert patched.refresh_stale_businesses(older_than_days=90) == 1
    session.expire_all()
    by_cid = {b.cid: b.status for b in session.query(Business).all()}
    assert by_cid["old"] == BusinessStatus.DISCOVERED
    assert by_cid["new"] == BusinessStatus.SCORED


def test_poll_queued_runs_returns_none_when_nothing_is_queued(patched, session):
    assert patched.poll_queued_runs() is None


def test_poll_queued_runs_executes_the_claimed_run(patched, session, monkeypatch):
    session.add(Run(status="queued", source="ui",
                    search_plan={"vertical": "hvac", "location": "Houston, TX"}))
    session.commit()

    executed: list[int] = []
    monkeypatch.setattr(patched, "execute_run",
                        lambda run_id, **kw: executed.append(run_id))

    claimed = patched.poll_queued_runs()

    assert claimed is not None and executed == [claimed]


def test_a_job_never_raises_into_the_scheduler_thread(patched, session, monkeypatch):
    """An exception escaping a job kills it for the life of the process. It
    must be logged and swallowed instead."""
    session.add(Run(status="queued", source="ui", search_plan={}))
    session.commit()

    def boom(run_id, **kw):
        raise RuntimeError("stage exploded")

    monkeypatch.setattr(patched, "execute_run", boom)

    patched.poll_queued_runs()          # must not raise


def test_reset_stuck_runs_with_a_zero_cutoff_requeues_anything_running(
        patched, session):
    """What the app's startup call passes.

    Under ADR-010 there is one container with one in-process scheduler, so
    a freshly started process owns no in-flight runs: anything still
    `running` at startup is by definition orphaned by the process that
    died, however recently it started.
    """
    session.add(Run(status="running", source="ui", search_plan={},
                    started_at=datetime.utcnow() - timedelta(seconds=1)))
    session.commit()

    assert patched.reset_stuck_runs(max_age_hours=0) == 1
    session.expire_all()
    assert session.query(Run).one().status == "queued"


def test_build_scheduler_registers_reset_stuck_runs_hourly(patched):
    """`reset_stuck_runs` must also be on a timer, not startup-only.

    Startup-only meant a process restarting within an hour of a run
    starting skipped that row and nothing ever re-checked it: stranded
    permanently. The hourly job is correct under any topology; the
    startup call (cutoff 0) only makes recovery immediate.
    """
    jobs = {j.id: j for j in patched.build_scheduler().get_jobs()}

    assert set(jobs) == {"poll_queued_runs", "reset_stuck_runs",
                         "retry_failed_businesses", "refresh_stale_businesses"}
    assert str(jobs["reset_stuck_runs"].trigger) == "interval[1:00:00]"
