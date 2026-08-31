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
# `on_stage` is called with each stage's outcome the moment that stage
# returns, so a caller can stream progress. The service itself never
# prints: it has to stay usable from the API and the scheduler, where
# writing to stdout is wrong.
StageObserver = Callable[[str, StageReport], None]

__all__ = ["Providers", "RunResult", "RunAlreadyComplete", "SessionFactory",
           "StageObserver", "budget_guard", "execute_run", "live_providers"]


class RunAlreadyComplete(Exception):
    """Raised when `execute_run` is handed a run that already finished.

    The CLI never hits this -- it creates a fresh `Run` per invocation --
    but the API and the scheduler both pass an *existing* run_id, so a
    double-POST, a retry, or an overlapping poll would otherwise flip a
    `complete` run back to `running` and re-bill all seven stages. Named
    (rather than a bare ValueError) so those callers can catch exactly
    this and answer 409 instead of 500.
    """


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
                session_factory: SessionFactory = get_session,
                on_stage: StageObserver | None = None) -> RunResult:
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

    `on_stage`, if given, is called with `(stage_name, report)` as each
    stage finishes -- before the next one starts and before any failure
    unwinds -- so a caller can stream progress and still see which stages
    succeeded when a later one crashes.

    A `complete` run is refused with `RunAlreadyComplete` before anything
    is written or spent. `running` is *allowed*: the scheduler claims a run
    by flipping queued->running before calling in, so refusing it would
    deadlock the poller. `queued` (the CLI) and `failed` (a deliberate
    operator retry, which resumes from the businesses' statuses rather
    than restarting) are allowed too.
    """
    settings = get_settings()

    with session_factory() as s:
        run = s.query(Run).filter_by(id=run_id).one_or_none()
        if run is None:
            raise ValueError(f"no such run: {run_id}")
        if run.status == "complete":
            # Refused before the status write and before a single provider
            # call: re-executing a finished run re-bills every stage.
            raise RunAlreadyComplete(
                f"run {run_id} is already complete; refusing to re-execute it")
        plan_args: dict[str, Any] = dict(run.search_plan)
        ceiling = run.max_cost_usd
        if run.status != "running":
            run.status = "running"
            run.started_at = run.started_at or datetime.utcnow()
        s.commit()

    try:
        # Inside the try, not above it: `live_providers()` constructs the
        # three paid adapters and can raise (an empty FIRECRAWL_KEY passes
        # pydantic, then `Firecrawl(api_key="")` raises ValueError). The
        # Run is already committed as `running` by this point, so a raise
        # from here with no terminal write strands it -- and a poller
        # claiming one run every 30 seconds strands all of them, silently.
        providers = providers or live_providers()
        vertical: str = plan_args["vertical"]
        verticals_cfg = yaml.safe_load((CONFIG / "verticals.yaml").read_text())
        locations_cfg = yaml.safe_load((CONFIG / "locations.yaml").read_text())
        plan = build_search_plan(
            vertical, plan_args.get("state"), plan_args.get("location"),
            verticals_cfg, locations_cfg,
            # `.get("pages", 5)` and not `... or 5`: `pages: 0` is a
            # legitimate instruction to search nothing, and `or` would
            # silently turn it into five pages per query.
            pages_per_query=plan_args.get("pages", 5))
        ruleset_path = (CONFIG / "rulesets"
                        / f"{verticals_cfg[vertical]['ruleset']}.yaml")
        ruleset = read_ruleset_file(ruleset_path)
        ruleset_definition = read_ruleset_definition(ruleset_path)
    except Exception:
        # The Run has already been flipped to `running` above, so a failed
        # provider construction or a bad search_plan (unknown vertical,
        # neither state nor location) must reach a terminal state here too
        # -- otherwise it is stranded at `running` forever, which is the
        # exact bug the per-stage handler below exists to prevent.
        error = f"setup failed: {traceback.format_exc()[-2000:]}"
        _terminal(session_factory, run_id, "failed", error)
        raise

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
            result.stages.append((name, report))
            if on_stage is not None:
                # Reported here, not after the loop: on the re-raise path a
                # buffered summary is lost entirely, which is precisely when
                # the operator most needs to know how far the run got.
                #
                # Inside the `try`, not after it: the observer belongs to the
                # caller and can raise. The CLI passes `echo_stage`, and
                # `typer.echo` raises BrokenPipeError on a closed stdout
                # (`python -m cli run-all ... | head`). Called outside, that
                # left the Run at `running` with no finished_at -- the one
                # in-process path that still stranded a run. The exception
                # still propagates; the handler below just makes sure the
                # terminal write lands first, and the stored traceback names
                # the observer frame so it is not mistaken for a stage bug.
                on_stage(name, report)
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
