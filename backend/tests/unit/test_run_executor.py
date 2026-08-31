"""`execute_run` is the single implementation of the run sequence that the
CLI, the API and the scheduler all share. These tests pin the behaviour
that `cli.py`'s `run_all` used to own outright: the seven-stage order, the
budget stop, the terminal-state write on every exit path, and
resumability.
"""
import os

# `app.services.run_executor` imports `app.core.db`, which builds a
# SQLAlchemy Engine at import time from `Settings.database_url`, so a
# syntactically valid (but never-connected-to, since `session_factory` is
# injected below) URL must exist in the environment before the service is
# imported. Mirrors the same guard in tests/api/conftest.py and
# tests/integration/test_cli.py.
os.environ.setdefault("DATABASE_URL",
                      "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test")
os.environ.setdefault("SERPER_KEY", "test-serper-key")
os.environ.setdefault("FIRECRAWL_KEY", "test-firecrawl-key")

from datetime import datetime

import pytest

from app.clients.fakes import FakeReviewProvider, FakeSearchProvider, FakeWebScraper
from app.models.business import Business
from app.models.derived import ApiCall, Score
from app.models.run import Run
from app.services.run_executor import Providers, execute_run


@pytest.fixture
def providers():
    return Providers(search=FakeSearchProvider(), scraper=FakeWebScraper(),
                     reviews=FakeReviewProvider([]))


@pytest.fixture
def queued_run(session):
    r = Run(status="queued", source="ui",
            search_plan={"vertical": "hvac", "state": None,
                         "location": "Houston, TX", "pages": 1})
    session.add(r)
    session.commit()
    return r


def _factory(session):
    """A session_factory that hands back the rolled-back test session."""
    from contextlib import contextmanager

    @contextmanager
    def f():
        yield session
    return f


def test_execute_run_walks_every_stage_in_order(session, queued_run, providers):
    result = execute_run(queued_run.id, providers=providers,
                         session_factory=_factory(session))

    assert result.status == "complete"
    assert [name for name, _ in result.stages] == [
        "discover", "scrape", "extract", "score", "enrich", "extract", "score"]


def test_execute_run_produces_scored_businesses(session, queued_run, providers):
    execute_run(queued_run.id, providers=providers,
                session_factory=_factory(session))

    assert session.query(Score).count() > 0


def test_execute_run_marks_the_run_complete_with_a_finish_time(
        session, queued_run, providers):
    execute_run(queued_run.id, providers=providers,
                session_factory=_factory(session))

    session.expire_all()
    run = session.query(Run).filter_by(id=queued_run.id).one()
    assert run.status == "complete"
    assert run.finished_at is not None
    assert run.actual_cost is not None


def test_execute_run_stops_and_fails_when_the_budget_is_exceeded(
        session, queued_run, providers):
    """A ceiling already blown before the first stage must stop the run
    without calling a single provider."""
    # `created_at` is NOT NULL on api_calls (every other writer stamps it
    # with datetime.utcnow(); see discover.py / scrape_site.py).
    session.add(ApiCall(provider="serper", endpoint="maps", credits=1,
                        cost_usd=99.0, status_code=200, run_id=queued_run.id,
                        created_at=datetime.utcnow()))
    queued_run.max_cost_usd = 0.01
    session.commit()

    result = execute_run(queued_run.id, providers=providers,
                         session_factory=_factory(session))

    assert result.status == "failed"
    assert "budget" in (result.error or "").lower()
    assert providers.search.calls == []
    session.expire_all()
    assert session.query(Run).filter_by(id=queued_run.id).one().status == "failed"


def test_execute_run_reraises_a_non_budget_failure_after_marking_the_run(
        session, queued_run):
    """A crash must still move the Run to a terminal state, but must NOT be
    swallowed -- the traceback has to stay visible."""
    class Boom:
        def search(self, *a, **k):
            raise RuntimeError("provider exploded")

    providers = Providers(search=Boom(), scraper=FakeWebScraper(),
                          reviews=FakeReviewProvider([]))

    with pytest.raises(RuntimeError, match="provider exploded"):
        execute_run(queued_run.id, providers=providers,
                    session_factory=_factory(session))

    session.expire_all()
    run = session.query(Run).filter_by(id=queued_run.id).one()
    assert run.status == "failed"
    assert run.finished_at is not None
    assert "discover" in (run.error or "")


def test_execute_run_leaves_unreached_businesses_resumable(
        session, queued_run, providers):
    """Businesses the run never got to must keep their status, so a second
    run continues rather than starting over."""
    execute_run(queued_run.id, providers=providers,
                session_factory=_factory(session))

    from app.models.business import BusinessStatus
    statuses = {b.status for b in session.query(Business).all()}
    assert BusinessStatus.FAILED not in statuses


def test_execute_run_raises_for_an_unknown_run_id(session, providers):
    with pytest.raises(ValueError, match="no such run"):
        execute_run(999999, providers=providers,
                    session_factory=_factory(session))
