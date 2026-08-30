"""Drives the actual Typer CLI (not the stage classes directly) so a
regression in `cli.py` itself — wrong stage order, a dropped stage, no
`Run`/budget wiring — is caught. Uses fakes for every external provider;
no real API calls are made. `app.core.db` builds a SQLAlchemy Engine at
import time from `Settings.database_url`, so a syntactically valid (but
never-connected-to, since `get_session` is monkeypatched below) URL must
exist in the environment before `cli` is imported.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL",
                      "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test")
os.environ.setdefault("SERPER_KEY", "test-serper-key")
os.environ.setdefault("FIRECRAWL_KEY", "test-firecrawl-key")

# `cli.py` is a top-level script module living at the backend/ repo root,
# not part of the installed `leadgen` package (only `app` is registered by
# the editable install), so it is only importable when that directory is
# on sys.path -- true for `python -m cli` (run from backend/), not for
# pytest, which inserts tests/integration/ instead.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

import cli
from app.clients.fakes import FakeReviewProvider, FakeSearchProvider, FakeWebScraper
from app.clients.protocols import ReviewRecord
from app.models.business import Business, BusinessStatus
from app.models.derived import ApiCall, Score, Signals
from app.models.run import Run
from app.services.budget import spend_usd

runner = CliRunner()

# The Houston fixture business used to check the enrich -> extract -> score
# loop below (see backend/tests/fixtures/serper_maps_houston_hvac.json).
TARGET_CID = "16433610908791049931"


def _recent_iso(days: int = 5) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


@pytest.fixture
def cli_env(session, monkeypatch):
    """Points the CLI's DB access at the shared per-test `session` fixture
    (so every stage a single `run-all` invocation triggers operates in the
    same transaction, which is rolled back at teardown like every other
    test in this suite) and swaps every real API client for a fake, so
    `run-all` can be driven through CliRunner with zero live network
    calls. `SerperClient`/`FirecrawlScraper`/`SerpApiReviewProvider` are
    ordinary module-global names referenced by `cli.py`'s command bodies,
    so monkeypatching them here (a seam that already exists) is enough --
    no changes to how cli.py constructs its providers were needed."""

    @contextmanager
    def _fake_get_session():
        yield session

    monkeypatch.setattr(cli, "get_session", _fake_get_session)
    monkeypatch.setattr(cli, "SerperClient", lambda: FakeSearchProvider())
    monkeypatch.setattr(cli, "FirecrawlScraper", lambda: FakeWebScraper())

    # Three reviews mentioning an unanswered call trips the ruleset's
    # missed_call_complaints rule (threshold >= 3, config/rulesets/hvac_v1.yaml).
    complaint_reviews = [
        ReviewRecord(iso_date=_recent_iso(), snippet="nobody answered")
        for _ in range(3)
    ]
    monkeypatch.setattr(cli, "SerpApiReviewProvider",
                        lambda: FakeReviewProvider(complaint_reviews))
    return session


def _invoke_run_all(extra_args: list[str] | None = None):
    args = ["run-all", "hvac", "--location", "Houston, TX", "--pages", "1"]
    if extra_args:
        args += extra_args
    return runner.invoke(cli.app, args)


def test_run_all_with_no_ceiling_runs_to_completion(cli_env):
    result = _invoke_run_all()
    assert result.exit_code == 0, result.output

    scored = cli_env.query(Business).filter_by(status=BusinessStatus.SCORED).all()
    assert len(scored) > 0

    run = cli_env.query(Run).one()
    assert run.status == "complete"
    assert run.finished_at is not None
    assert run.max_cost_usd is None


def test_run_all_writes_api_calls_carrying_the_run_id_so_spend_usd_sees_them(cli_env):
    result = _invoke_run_all()
    assert result.exit_code == 0, result.output

    run = cli_env.query(Run).one()
    calls = cli_env.query(ApiCall).filter(ApiCall.run_id == run.id).all()
    assert len(calls) > 0
    assert all(c.run_id == run.id for c in calls)
    assert spend_usd(cli_env, run.id) > 0


def test_run_all_stops_early_when_the_ceiling_is_exceeded(cli_env):
    """Finding 1+2: a ceiling of $0 must trip after the very first stage
    (discover) logs any spend at all, stopping the run before scrape ever
    runs -- proving check_budget is actually wired into run-all, not dead
    code, and that it fires BETWEEN stages rather than after the whole run
    has already overspent."""
    result = _invoke_run_all(["--max-cost", "0"])
    assert result.exit_code != 0
    assert "budget" in result.output.lower()

    run = cli_env.query(Run).one()
    assert run.status == "failed"
    assert run.error is not None

    # discover ran (there are DISCOVERED businesses and serper ApiCall rows)...
    assert cli_env.query(Business).filter_by(status=BusinessStatus.DISCOVERED).count() > 0
    # ...but no later stage ever executed.
    assert cli_env.query(Business).filter_by(status=BusinessStatus.SITE_SCRAPED).count() == 0
    assert cli_env.query(Business).filter_by(status=BusinessStatus.SCORED).count() == 0
    assert cli_env.query(ApiCall).filter_by(provider="firecrawl").count() == 0


def test_run_all_second_scoring_pass_reflects_review_enrichment(cli_env):
    """Finding 4: the correct order is discover -> scrape -> extract ->
    score -> enrich -> extract -> score. `enrich` resets a business from
    SCORED back to SITE_SCRAPED (FetchReviewsStage), so if the second
    extract/score pass were dropped from run-all, this business would be
    stuck at SITE_SCRAPED (never re-scored) and its Score row would still
    be the stale pre-enrichment one with no missed_call_complaints signal
    -- either half of this assertion fails if that pass is removed."""
    result = _invoke_run_all()
    assert result.exit_code == 0, result.output

    business = cli_env.query(Business).filter_by(cid=TARGET_CID).one()
    assert business.status == BusinessStatus.SCORED

    signals = cli_env.query(Signals).filter_by(business_id=business.id).one()
    assert signals.missed_call_complaints_90d == 3

    score = cli_env.query(Score).filter_by(
        business_id=business.id, ruleset_version="hvac_v1").one()
    reasons_by_rule = {r["rule"]: r for r in score.reasons}
    assert "missed_call_complaints" in reasons_by_rule
    assert reasons_by_rule["missed_call_complaints"]["matched"] is True
