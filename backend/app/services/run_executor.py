"""The one implementation of a full pipeline run.

The CLI, the API and the scheduler all call `execute_run`. There is no
second copy of the stage list: Plan 1's final review found the same logic
written three different ways across components, and this is exactly the
seam where that would happen again. Everything here was lifted verbatim
out of `cli.py`'s `run_all`, including the comments that record why each
branch exists.
"""
import traceback
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import structlog
import yaml
from sqlalchemy.orm import Session

from app.clients.protocols import ReviewProvider, SearchProvider, WebScraper
from app.core.config import get_settings
from app.core.db import get_session
from app.models.run import Run
from app.pipeline.base import StageReport
from app.pipeline.discover import DiscoverStage
from app.pipeline.extract_signals import ExtractSignalsStage
from app.pipeline.fetch_reviews import FetchReviewsStage
from app.pipeline.score import ScoreStage
from app.pipeline.scrape_site import ScrapeSiteStage
from app.services.budget import BudgetExceeded, check_budget, spend_usd
from app.services.rulesets import read_ruleset_definition, read_ruleset_file
from app.services.search_plan import build_search_plan

log = structlog.get_logger()
CONFIG = Path("config")

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass
class Providers:
    """The three paid adapters, injected so tests can pass fakes."""

    search: SearchProvider
    scraper: WebScraper
    reviews: ReviewProvider


@dataclass
class RunResult:
    run_id: int
    status: str
    stages: list[tuple[str, StageReport]] = field(default_factory=list)
    error: str | None = None


def live_providers() -> Providers:
    """The real, paid adapters. Imported lazily so importing this module
    (which the API does at startup) does not drag in the HTTP clients."""
    from app.clients.firecrawl import FirecrawlScraper
    from app.clients.serpapi_reviews import SerpApiReviewProvider
    from app.clients.serper import SerperClient

    return Providers(search=SerperClient(), scraper=FirecrawlScraper(),
                     reviews=SerpApiReviewProvider())


def budget_guard(run_id: int | None, max_cost: float | None
                 ) -> Callable[[Session], None] | None:
    """A per-business guard for the spending stages.

    Public because `cli.py`'s standalone `discover`/`scrape` commands build
    the same guard; one definition, two callers.

    `check_budget` used to be called only at stage boundaries. `scrape` is
    the only stage that spends meaningful cash and it ran to completion
    once entered, so `--max-cost 0.05` still spent ~$0.60 (I1). Returning
    None when there is no ceiling keeps the no-limit path free of queries.
    """
    if max_cost is None:
        return None

    def check(session: Session) -> None:
        check_budget(session, run_id, max_cost)

    return check


def _terminal(session_factory: SessionFactory, run_id: int, status: str,
              error: str | None) -> None:
    """Move the Run to a terminal state.

    Called on every exit path. A run stranded at status="running" with no
    `finished_at` is invisible to monitoring and can never be reconciled --
    that was the round-2 review finding this function exists to prevent.
    """
    with session_factory() as s:
        run = s.query(Run).filter_by(id=run_id).one()
        run.status = status
        run.error = error
        run.finished_at = datetime.utcnow()
        run.actual_cost = spend_usd(s, run_id)
        s.commit()


def execute_run(run_id: int, *, providers: Providers | None = None,
                session_factory: SessionFactory = get_session) -> RunResult:
    """Run every stage for `run_id`, in order, under its budget ceiling.

    Discover -> scrape -> extract -> score -> enrich -> extract -> score.
    The Run's id is threaded through every stage call so `ApiCall` rows
    (and therefore `spend_usd`/`check_budget`) are attributed to this run.
    If the Run carries a `max_cost_usd`, the budget is checked before each
    stage AND, inside the two spending stages, before each business/query
    -- so the ceiling can be overshot by at most one business's cost.
    Checking only at stage boundaries was not enough: `scrape` runs to
    completion once entered (I1).

    A stage that reports `aborted` (circuit breaker tripped, or the budget
    ran out mid-stage) stops the run and marks the Run failed. Businesses
    that were not reached keep their status, so the run is resumable.
    """
    providers = providers or live_providers()
    settings = get_settings()

    with session_factory() as s:
        run = s.query(Run).filter_by(id=run_id).one_or_none()
        if run is None:
            raise ValueError(f"no such run: {run_id}")
        plan_args: dict[str, Any] = dict(run.search_plan)
        ceiling = run.max_cost_usd
        if run.status != "running":
            run.status = "running"
            run.started_at = run.started_at or datetime.utcnow()
        s.commit()

    vertical: str = plan_args["vertical"]
    verticals_cfg = yaml.safe_load((CONFIG / "verticals.yaml").read_text())
    locations_cfg = yaml.safe_load((CONFIG / "locations.yaml").read_text())
    plan = build_search_plan(vertical, plan_args.get("state"),
                             plan_args.get("location"),
                             verticals_cfg, locations_cfg,
                             pages_per_query=plan_args.get("pages") or 5)
    ruleset_path = CONFIG / "rulesets" / f"{verticals_cfg[vertical]['ruleset']}.yaml"
    ruleset = read_ruleset_file(ruleset_path)
    ruleset_definition = read_ruleset_definition(ruleset_path)

    budget_check = budget_guard(run_id, ceiling)

    def _discover(s: Session) -> StageReport:
        return DiscoverStage(providers.search).discover(
            s, run_id, plan, budget_check=budget_check)

    def _scrape(s: Session) -> StageReport:
        return ScrapeSiteStage(
            providers.scraper,
            per_segment=settings.stratified_per_segment,
        ).run(s, run_id, budget_check=budget_check)

    def _extract(s: Session) -> StageReport:
        return ExtractSignalsStage().run(s, run_id)

    def _score(s: Session) -> StageReport:
        return ScoreStage(ruleset, definition=ruleset_definition).run(s, run_id)

    def _enrich(s: Session) -> StageReport:
        return FetchReviewsStage(
            providers.reviews, top_n=settings.enrichment_top_n,
            monthly_ceiling=settings.serpapi_monthly_ceiling,
            ruleset_version=ruleset.version).run(s, run_id)

    # The ADR-020 loop: enrich, then re-derive signals and re-score over
    # the richer, review-enriched data `enrich` just fetched. Dropping the
    # second extract/score pass silently leaves review-derived signals
    # unscored -- the business is left at SITE_SCRAPED with a stale Score.
    stages: list[tuple[str, Callable[[Session], StageReport]]] = [
        ("discover", _discover),
        ("scrape", _scrape),
        ("extract", _extract),
        ("score", _score),
        ("enrich", _enrich),
        ("extract", _extract),
        ("score", _score),
    ]

    result = RunResult(run_id=run_id, status="complete")

    for name, fn in stages:
        try:
            with session_factory() as s:
                check_budget(s, run_id, ceiling)
                report = fn(s)
                s.commit()
        except BudgetExceeded as exc:
            log.warning("run.budget_exceeded", run_id=run_id, stage=name,
                        reason=str(exc))
            result.status = "failed"
            result.error = f"budget ceiling reached before '{name}': {exc}"
            _terminal(session_factory, run_id, "failed", result.error)
            return result
        except Exception:
            # Any non-budget failure (a real provider error, a bug in a
            # stage, etc.) must still move the Run to a terminal state --
            # otherwise it is stranded at status="running" forever with no
            # finished_at. Unlike the budget path above this does NOT
            # convert to a clean exit: the original exception is re-raised
            # so it stays visible (traceback and all) rather than being
            # swallowed into a quiet non-zero exit.
            error = f"{name} failed: {traceback.format_exc()[-2000:]}"
            _terminal(session_factory, run_id, "failed", error)
            raise

        result.stages.append((name, report))

        if report.aborted:
            # `StageReport.aborted` was once echoed and then ignored: a
            # tripped circuit breaker (or a mid-stage budget stop) let the
            # run continue, mark itself `complete` and exit 0, handing the
            # operator a CSV missing 90% of its leads (I3).
            log.error("run.stage_aborted", run_id=run_id, stage=name,
                      reason=report.reason)
            result.status = "failed"
            result.error = f"stage aborted: {report.reason}"
            _terminal(session_factory, run_id, "failed", result.error)
            return result

    _terminal(session_factory, run_id, "complete", None)
    return result
