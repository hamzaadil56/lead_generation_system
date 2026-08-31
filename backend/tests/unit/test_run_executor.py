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
from app.services.run_executor import (
    Providers, RunAlreadyComplete, execute_run)


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


def test_execute_run_resolves_an_uppercase_state_via_build_search_plan(
        session, providers):
    """A run queued by the CLI or the API with `state="TX"` must not strand
    at `running` because `config/locations.yaml` keys states lowercase
    (`tx`). `build_search_plan` is what normalises now (search_plan.py), so
    this exercises the real path `execute_run` takes -- not a mock of it."""
    run = Run(status="queued", source="cli",
             search_plan={"vertical": "hvac", "state": "TX",
                          "location": None, "pages": 1})
    session.add(run)
    session.commit()

    result = execute_run(run.id, providers=providers,
                         session_factory=_factory(session))

    assert result.status == "complete"


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


# --- Fix round 1, Finding 1: re-entry -------------------------------------

def test_execute_run_refuses_to_re_execute_a_complete_run(
        session, queued_run, providers):
    """The CLI creates a fresh Run each time, but the API and the scheduler
    both pass an existing run_id -- a double-POST or an overlapping poll
    would otherwise flip a finished run back to `running` and re-bill all
    seven stages."""
    queued_run.status = "complete"
    queued_run.finished_at = datetime.utcnow()
    session.commit()

    with pytest.raises(RunAlreadyComplete):
        execute_run(queued_run.id, providers=providers,
                    session_factory=_factory(session))

    # Refused before anything ran, not merely after the fact.
    assert providers.search.calls == []
    assert providers.scraper.calls == []
    session.expire_all()
    run = session.query(Run).filter_by(id=queued_run.id).one()
    assert run.status == "complete"


def test_execute_run_allows_a_run_already_marked_running(
        session, queued_run, providers):
    """Task 10's scheduler claims a run by flipping queued->running BEFORE
    calling execute_run. Refusing `running` would deadlock the poller."""
    queued_run.status = "running"
    queued_run.started_at = datetime.utcnow()
    session.commit()

    result = execute_run(queued_run.id, providers=providers,
                         session_factory=_factory(session))

    assert result.status == "complete"
    assert providers.search.calls != []


def test_execute_run_allows_an_operator_to_retry_a_failed_run(
        session, queued_run, providers):
    """A failed run is resumable: the businesses' statuses make the retry
    continue rather than start over."""
    queued_run.status = "failed"
    queued_run.error = "discover failed: boom"
    queued_run.finished_at = datetime.utcnow()
    session.commit()

    result = execute_run(queued_run.id, providers=providers,
                         session_factory=_factory(session))

    assert result.status == "complete"
    session.expire_all()
    run = session.query(Run).filter_by(id=queued_run.id).one()
    assert run.status == "complete"
    assert run.error is None


def test_execute_run_still_runs_a_queued_run(session, queued_run, providers):
    assert queued_run.status == "queued"

    result = execute_run(queued_run.id, providers=providers,
                         session_factory=_factory(session))

    assert result.status == "complete"


# --- Fix round 1, Finding 2: pages=0 --------------------------------------

def test_execute_run_treats_pages_zero_as_search_nothing(session, providers):
    """`pages: 0` means zero pages per query. `.get("pages") or 5` swallowed
    the 0 and searched five pages of every query instead."""
    run = Run(status="queued", source="ui",
              search_plan={"vertical": "hvac", "state": None,
                           "location": "Houston, TX", "pages": 0})
    session.add(run)
    session.commit()

    result = execute_run(run.id, providers=providers,
                         session_factory=_factory(session))

    assert result.status == "complete"
    assert providers.search.calls == []


def test_execute_run_defaults_to_five_pages_when_pages_is_absent(
        session, providers):
    run = Run(status="queued", source="ui",
              search_plan={"vertical": "hvac", "state": None,
                           "location": "Houston, TX"})
    session.add(run)
    session.commit()

    execute_run(run.id, providers=providers, session_factory=_factory(session))

    # The ceiling is 5 pages per query, but the Houston fixture returns an
    # empty page 2, which stops DiscoverStage's page walk -- so the
    # observable proof that the default is neither 0 nor 1 is that each of
    # the 4 search terms was asked for a second page.
    assert {page for _, page in providers.search.calls} == {1, 2}
    assert len(providers.search.calls) == 8


# --- Fix round 1, Finding 3: streaming stage outcomes ---------------------

def test_execute_run_reports_each_stage_as_it_completes(
        session, queued_run, providers):
    seen: list[str] = []
    execute_run(queued_run.id, providers=providers,
                session_factory=_factory(session),
                on_stage=lambda name, report: seen.append(name))

    assert seen == ["discover", "scrape", "extract", "score", "enrich",
                    "extract", "score"]


def test_execute_run_reports_completed_stages_before_a_later_stage_crashes(
        session, queued_run, providers, monkeypatch):
    """The stages that succeeded must already have been reported by the
    time the crash unwinds -- a summary buffered until `execute_run`
    returns is lost entirely on the re-raise path."""
    class BoomExtract:
        def run(self, *a, **k):
            raise RuntimeError("extract exploded")

    monkeypatch.setattr("app.services.run_executor.ExtractSignalsStage",
                        BoomExtract)
    seen: list[str] = []

    with pytest.raises(RuntimeError, match="extract exploded"):
        execute_run(queued_run.id, providers=providers,
                    session_factory=_factory(session),
                    on_stage=lambda name, report: seen.append(name))

    assert seen == ["discover", "scrape"]


def test_execute_run_marks_a_bad_search_plan_terminal_instead_of_stranding_it(
        session, providers):
    """The Run is flipped to `running` before the plan is built, so a plan
    that cannot be built must still reach a terminal state -- same reason
    the per-stage handler exists."""
    run = Run(status="queued", source="ui",
              search_plan={"vertical": "hvac", "state": None,
                           "location": None, "pages": 1})
    session.add(run)
    session.commit()

    with pytest.raises(ValueError, match="state or location"):
        execute_run(run.id, providers=providers,
                    session_factory=_factory(session))

    session.expire_all()
    reloaded = session.query(Run).filter_by(id=run.id).one()
    assert reloaded.status == "failed"
    assert reloaded.finished_at is not None
    assert "setup failed" in (reloaded.error or "")


def test_execute_run_writes_terminal_state_when_provider_construction_fails(
        session, queued_run, monkeypatch):
    """The fourth raise path, found in fix round 1.

    `live_providers()` is called *after* the Run has been committed as
    `running`. It is reachable: pydantic accepts an empty `FIRECRAWL_KEY`,
    and `Firecrawl(api_key="")` then raises ValueError. With the call
    outside every `try`, a scheduler claiming a run every 30 seconds
    stranded every one of them at `running` with `finished_at=None` and
    `error=None`, while `/health` stayed green -- exactly the silent
    degradation the terminal-state rule exists to prevent.
    """
    import app.services.run_executor as mod

    def no_providers() -> Providers:
        raise ValueError("Firecrawl: no API key provided")

    monkeypatch.setattr(mod, "live_providers", no_providers)

    # The exception must still propagate: the caller (and the poller's own
    # log.exception) has to see it.
    with pytest.raises(ValueError):
        execute_run(queued_run.id, session_factory=_factory(session))

    session.expire_all()
    run = session.query(Run).filter_by(id=queued_run.id).one()
    assert run.status == "failed"
    assert run.finished_at is not None
    assert run.error is not None
