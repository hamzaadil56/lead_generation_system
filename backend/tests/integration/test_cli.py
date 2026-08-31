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
def scheduler_env(session, monkeypatch):
    """`reset_stuck_runs` lives in `app.scheduler` and resolves
    `get_session` as that module's global, so patching `cli.get_session`
    is not enough -- without this the command would run against the real
    database instead of the rolled-back fixture session."""
    import app.scheduler as sched

    @contextmanager
    def _fake_get_session():
        yield session

    monkeypatch.setattr(sched, "get_session", _fake_get_session)
    return session


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


class _BoomSearchProvider:
    """Simulates a real provider error propagating unwrapped, exactly like
    `DiscoverStage.discover`'s `self._provider.search()` call at
    backend/app/pipeline/discover.py:32, which has no try/except around
    it. Used to prove run-all's non-budget exception path (round 2 fix)."""

    def search(self, query: str, page: int = 1):
        raise RuntimeError("boom: provider exploded")


def test_run_all_reaches_a_terminal_state_when_a_stage_raises_a_non_budget_error(
        cli_env, monkeypatch):
    """Round 2 finding: only BudgetExceeded was caught in run-all, so any
    other exception (e.g. a real provider error) left the Run row stuck at
    status="running" forever, with no finished_at. The fix must reach a
    terminal Run state on every exit path AND let the original exception
    keep surfacing -- a crashed run must still look crashed, not exit
    clean."""
    monkeypatch.setattr(cli, "SerperClient", lambda: _BoomSearchProvider())

    result = _invoke_run_all()

    assert result.exit_code != 0
    assert result.exception is not None
    assert isinstance(result.exception, RuntimeError)
    assert "boom" in str(result.exception)

    run = cli_env.query(Run).one()
    assert run.status in ("failed", "complete")  # terminal, never "running"
    assert run.status != "running"
    assert run.finished_at is not None


def test_max_cost_is_enforced_inside_scrape_not_only_between_stages(cli_env):
    """I1: `--max-cost 0.05` still spent ~$0.60. The ceiling was checked
    once per stage boundary, and `scrape` — the only real cash spender —
    runs to completion once entered, so the guard could not bound it.

    With a $0.02 ceiling: discover logs 4 queries x 3 Serper credits =
    $0.012, then scrape may bill only a handful of $0.002 Firecrawl calls
    before the per-business check trips. Overshoot is bounded by one
    business's cost. Before the fix scrape ran to completion and nothing
    was left DISCOVERED."""
    result = _invoke_run_all(["--max-cost", "0.02"])
    assert result.exit_code != 0

    firecrawl_calls = cli_env.query(ApiCall).filter_by(provider="firecrawl").count()
    assert 0 < firecrawl_calls <= 8, firecrawl_calls
    assert spend_usd(cli_env, cli_env.query(Run).one().id) <= 0.023

    # Stopping mid-stage is clean: the rest are resumable, not FAILED.
    assert cli_env.query(Business).filter_by(
        status=BusinessStatus.DISCOVERED).count() > 0
    assert cli_env.query(Business).filter_by(
        status=BusinessStatus.FAILED).count() == 0

    run = cli_env.query(Run).one()
    assert run.status == "failed"
    assert run.finished_at is not None


class _OutOfCreditsScraper:
    def scrape(self, url):
        from app.core.errors import RunPermanentError
        raise RunPermanentError("firecrawl: HTTP 402", status_code=402)


def test_an_aborted_stage_stops_run_all_and_exits_non_zero(cli_env, monkeypatch):
    """I3: `StageReport.aborted` was echoed and then ignored. Firecrawl
    401s five times, the breaker aborts `scrape`, and run-all used to
    carry on to extract/score/enrich, mark the Run `complete` and exit 0 —
    handing the operator a CSV that looks like a normal run and is missing
    90% of its leads."""
    monkeypatch.setattr(cli, "FirecrawlScraper", lambda: _OutOfCreditsScraper())

    result = _invoke_run_all()

    assert result.exit_code != 0
    run = cli_env.query(Run).one()
    assert run.status == "failed"
    assert run.finished_at is not None
    # Nothing downstream of the aborted stage may have run.
    assert cli_env.query(Score).count() == 0
    assert cli_env.query(Business).filter_by(
        status=BusinessStatus.SCORED).count() == 0


def test_export_threads_the_ruleset_version_from_the_cli(cli_env, tmp_path):
    """Deferred item 17 at the CLI seam: `export` must ask the vertical's
    ruleset for its version rather than assume "hvac_v1"."""
    import csv
    assert _invoke_run_all().exit_code == 0
    out = tmp_path / "leads.csv"

    result = runner.invoke(cli.app, ["export", "--out", str(out),
                                     "--vertical", "hvac"])
    assert result.exit_code == 0, result.output
    assert "hvac_v1" in result.output
    assert len(list(csv.DictReader(out.open(encoding="utf-8")))) > 0


class _BoomExtractStage:
    """Stands in for ExtractSignalsStage, the third stage in the sequence."""

    def run(self, *args, **kwargs):
        raise RuntimeError("boom: extract exploded")


def test_run_all_reports_completed_stages_before_a_later_stage_crashes(
        cli_env, monkeypatch):
    """Fix round 1, finding 3: stage results were buffered until
    `execute_run` returned and were therefore lost entirely on the
    re-raise path -- exactly when the operator most needs to know which
    stages got through before the crash."""
    monkeypatch.setattr("app.services.run_executor.ExtractSignalsStage",
                        _BoomExtractStage)

    result = _invoke_run_all()

    assert isinstance(result.exception, RuntimeError)
    # The two stages that finished were reported as they landed.
    assert "discover:" in result.output
    assert "scrape:" in result.output
    # The one that blew up was not.
    assert "extract:" not in result.output


def test_run_all_streams_every_stage_outcome_on_a_clean_run(cli_env):
    result = _invoke_run_all()
    assert result.exit_code == 0, result.output

    for stage_name in ("discover", "scrape", "extract", "score", "enrich"):
        assert f"{stage_name}:" in result.output


def test_run_all_creates_its_run_as_running_so_a_poller_cannot_claim_it(
        cli_env, monkeypatch):
    """C2 variant B: cross-process double execution through the queued gap.

    `run-all` used to commit the `Run` as `queued` and only *then*
    construct three provider clients before calling `execute_run`. ADR-017
    and the Dockerfile document the CLI as a second entrypoint into the
    same image and database, so during that gap the API container's
    30-second poller could `claim_next_queued_run` the row and walk all
    seven stages against the same run_id concurrently -- duplicated Serper
    and Firecrawl spend and two writers on the same business rows.
    `execute_run`'s re-entry guard cannot help: it deliberately allows
    `running` (refusing it would deadlock the poller).

    The CLI now creates the run as `running` with `started_at` set in the
    same transaction, so the poller's `status == "queued"` filter never
    sees it. This asserts a poller finds nothing to claim at the moment
    `execute_run` is entered -- the far end of the old window.
    """
    from app.repositories.runs import claim_next_queued_run

    claims: list[int | None] = []
    real_execute = cli.execute_run

    def spy_execute(run_id, **kwargs):
        claims.append(claim_next_queued_run(cli_env))
        return real_execute(run_id, **kwargs)

    monkeypatch.setattr(cli, "execute_run", spy_execute)

    result = _invoke_run_all()
    assert result.exit_code == 0, result.output

    assert claims == [None], (
        "a poller claimed the CLI's run out from under it; the run row was "
        "visible as `queued`")
    run = cli_env.query(Run).one()
    assert run.started_at is not None
    assert run.status == "complete"


def test_reset_stuck_runs_is_an_explicit_command_not_an_automatic_job(
        cli_env, scheduler_env):
    """C2: no automatic reconciliation, only an operator-invoked one.

    Without an ownership or heartbeat column no *automatic* reset is safe
    in a multi-process deployment: every cutoff is a guess about whether
    another process is still alive, and requeuing a live run makes the
    poller re-claim and concurrently re-execute it. An operator running
    this deliberately knows what is running; a timer never does.
    """
    from datetime import datetime as _dt

    cli_env.add(Run(status="running", source="cli", search_plan={},
                    started_at=_dt.utcnow() - timedelta(hours=48)))
    cli_env.add(Run(status="running", source="ui", search_plan={},
                    started_at=_dt.utcnow()))
    cli_env.commit()

    result = runner.invoke(cli.app, ["reset-stuck-runs",
                                     "--older-than-hours", "24"])

    assert result.exit_code == 0, result.output
    assert "1" in result.output
    cli_env.expire_all()
    by_source = {r.source: r for r in cli_env.query(Run).all()}
    assert by_source["cli"].status == "queued"
    assert by_source["cli"].started_at is None
    # The recent run belongs to a process that is very likely still alive.
    assert by_source["ui"].status == "running"


def test_reset_stuck_runs_defaults_to_a_conservative_cutoff(
        cli_env, scheduler_env):
    """The default must not requeue a run that started an hour ago: the
    whole risk this command carries is guessing that a live process is
    dead."""
    from datetime import datetime as _dt

    cli_env.add(Run(status="running", source="cli", search_plan={},
                    started_at=_dt.utcnow() - timedelta(hours=1)))
    cli_env.commit()

    result = runner.invoke(cli.app, ["reset-stuck-runs"])

    assert result.exit_code == 0, result.output
    cli_env.expire_all()
    assert cli_env.query(Run).one().status == "running"
