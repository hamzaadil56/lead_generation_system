import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

import typer
import yaml

from app.clients.firecrawl import FirecrawlScraper
from app.clients.serpapi_reviews import SerpApiReviewProvider
from app.clients.serper import SerperClient
from app.core.config import get_settings
from app.core.db import get_session
from app.models.run import Run
from app.pipeline.discover import DiscoverStage
from app.pipeline.extract_signals import ExtractSignalsStage
from app.pipeline.fetch_reviews import FetchReviewsStage
from app.pipeline.score import ScoreStage
from app.pipeline.scrape_site import ScrapeSiteStage
from app.services.budget import BudgetExceeded, check_budget, spend_usd
from app.services.export import export_leads
from app.services.outcomes import record_outcome
from app.services.rulesets import read_ruleset_definition, read_ruleset_file
from app.services.search_plan import build_search_plan

app = typer.Typer()
CONFIG = Path("config")


def _budget_check(run_id: int | None, max_cost: float | None):
    """A per-business guard for the spending stages.

    `check_budget` used to be called only at stage boundaries. `scrape` is
    the only stage that spends meaningful cash and it ran to completion
    once entered, so `--max-cost 0.05` still spent ~$0.60 (I1). Returning
    None when there is no ceiling keeps the no-limit path free of queries.
    """
    if max_cost is None:
        return None

    def check(session) -> None:
        check_budget(session, run_id, max_cost)

    return check


def _report(report) -> None:
    """Echo a StageReport and FAIL if the stage aborted.

    `StageReport.aborted` was echoed and then ignored: a tripped circuit
    breaker (or a budget stop) let `run-all` continue, mark the Run
    `complete` and exit 0, handing the operator a CSV missing 90% of its
    leads (I3).
    """
    typer.echo(report)
    if getattr(report, "aborted", False):
        typer.echo(f"stage aborted: {report.reason}", err=True)
        raise typer.Exit(code=1)


def _plan(vertical: str, state: str | None, location: str | None, pages: int):
    return build_search_plan(
        vertical, state, location,
        yaml.safe_load((CONFIG / "verticals.yaml").read_text()),
        yaml.safe_load((CONFIG / "locations.yaml").read_text()),
        pages_per_query=pages,
    )


def _ruleset_path(vertical: str) -> Path:
    cfg = yaml.safe_load((CONFIG / "verticals.yaml").read_text())
    return CONFIG / "rulesets" / f"{cfg[vertical]['ruleset']}.yaml"


def _ruleset(vertical: str):
    return read_ruleset_file(_ruleset_path(vertical))


def _ruleset_definition(vertical: str) -> dict:
    return read_ruleset_definition(_ruleset_path(vertical))


@app.command()
def discover(vertical: str, state: str | None = None, location: str | None = None,
             pages: int = 5, run_id: int | None = None,
             max_cost: float | None = None) -> None:
    with get_session() as s:
        report = DiscoverStage(SerperClient()).discover(
            s, run_id, _plan(vertical, state, location, pages),
            budget_check=_budget_check(run_id, max_cost))
        typer.echo(f"discovered: {report.processed}")
        if report.aborted:
            typer.echo(f"stage aborted: {report.reason}", err=True)
            raise typer.Exit(code=1)


@app.command()
def scrape(per_segment: int | None = None, run_id: int | None = None,
           max_cost: float | None = None) -> None:
    n = per_segment or get_settings().stratified_per_segment
    with get_session() as s:
        _report(ScrapeSiteStage(FirecrawlScraper(), per_segment=n)
                .run(s, run_id, budget_check=_budget_check(run_id, max_cost)))


@app.command()
def extract(run_id: int | None = None) -> None:
    with get_session() as s:
        _report(ExtractSignalsStage().run(s, run_id))


@app.command()
def score(vertical: str = "hvac", run_id: int | None = None) -> None:
    with get_session() as s:
        _report(ScoreStage(_ruleset(vertical),
                           definition=_ruleset_definition(vertical)).run(s, run_id))


@app.command()
def enrich(vertical: str = "hvac", top_n: int | None = None,
           run_id: int | None = None) -> None:
    settings = get_settings()
    with get_session() as s:
        _report(FetchReviewsStage(
            SerpApiReviewProvider(), top_n=top_n or settings.enrichment_top_n,
            monthly_ceiling=settings.serpapi_monthly_ceiling,
            ruleset_version=_ruleset(vertical).version).run(s, run_id))


@app.command("run-all")
def run_all(vertical: str, state: str | None = None, location: str | None = None,
            pages: int = 5,
            max_cost: float | None = typer.Option(
                None, "--max-cost",
                help="Cost ceiling in USD for this run. Unset means no limit.")
            ) -> None:
    """Discover -> scrape -> extract -> score -> enrich -> extract -> score.

    Creates a `Run` row up front and threads its id through every stage
    call so `ApiCall` rows (and therefore `spend_usd`/`check_budget`) can
    be attributed to this run. If `--max-cost` is given, the budget is
    checked before each stage AND, inside the two spending stages, before
    each business/query — so the ceiling can be overshot by at most one
    business's cost. Checking only at stage boundaries was not enough:
    `scrape` runs to completion once entered (I1).

    A stage that reports `aborted` (circuit breaker tripped, or the budget
    ran out mid-stage) stops the run, marks the Run failed and exits
    non-zero. Businesses that were not reached keep their status, so the
    run is resumable.
    """
    with get_session() as s:
        run = Run(status="running", source="cli",
                  search_plan={"vertical": vertical, "state": state,
                               "location": location, "pages": pages},
                  max_cost_usd=max_cost,
                  created_at=datetime.utcnow(), started_at=datetime.utcnow())
        s.add(run)
        s.commit()
        run_id = run.id

    stages: list[tuple[str, Callable[[], None]]] = [
        ("discover", lambda: discover(vertical, state, location, pages,
                                      run_id=run_id, max_cost=max_cost)),
        ("scrape", lambda: scrape(run_id=run_id, max_cost=max_cost)),
        ("extract", lambda: extract(run_id=run_id)),
        ("score", lambda: score(vertical, run_id=run_id)),
        ("enrich", lambda: enrich(vertical, run_id=run_id)),
        # The ADR-020 loop: re-derive signals and re-score over the richer,
        # review-enriched data that `enrich` just fetched.
        ("extract", lambda: extract(run_id=run_id)),
        ("score", lambda: score(vertical, run_id=run_id)),
    ]

    for stage_name, run_stage in stages:
        with get_session() as s:
            run_row = s.query(Run).filter_by(id=run_id).one()
            try:
                check_budget(s, run_id, run_row.max_cost_usd)
            except BudgetExceeded as exc:
                typer.echo(f"budget ceiling reached before '{stage_name}': {exc}",
                          err=True)
                run_row.status = "failed"
                run_row.error = str(exc)
                run_row.finished_at = datetime.utcnow()
                s.commit()
                raise typer.Exit(code=1) from exc

        try:
            run_stage()
        except Exception:
            # Any non-budget failure (a real provider error, a bug in a
            # stage, etc.) must still move the Run to a terminal state --
            # otherwise it is stranded at status="running" forever with no
            # finished_at. Unlike the budget-abort path above, this does
            # NOT convert to a clean typer.Exit: the original exception is
            # re-raised so it stays visible (traceback and all) rather than
            # being swallowed into a quiet non-zero exit.
            with get_session() as s:
                run_row = s.query(Run).filter_by(id=run_id).one()
                run_row.status = "failed"
                run_row.error = f"{stage_name} failed: {traceback.format_exc()[-2000:]}"
                run_row.finished_at = datetime.utcnow()
                s.commit()
            raise

    with get_session() as s:
        run_row = s.query(Run).filter_by(id=run_id).one()
        run_row.status = "complete"
        run_row.finished_at = datetime.utcnow()
        run_row.actual_cost = spend_usd(s, run_id)
        s.commit()


@app.command("export")
def export_cmd(out: Path = Path("leads.csv"), quadrant: str | None = None,
               min_fit: int = 0, vertical: str = "hvac") -> None:
    # `ruleset_version` was hardcoded to "hvac_v1" inside export_leads and
    # never threaded from here, so a second vertical exported 0 rows -- a
    # failure that reads as "no leads matched" rather than as a bug.
    version = _ruleset(vertical).version
    with get_session() as s:
        count = export_leads(s, quadrant, min_fit, out, ruleset_version=version)
        typer.echo(f"exported {count} ({version}) -> {out}")


@app.command()
def outcome(cid: str, status: str, notes: str | None = None) -> None:
    # Record what happened: new|contacted|replied|booked|won|lost
    with get_session() as s:
        record_outcome(s, cid, status, notes)
        typer.echo(f"{cid} -> {status}")


@app.command()
def spend(run_id: int | None = None) -> None:
    with get_session() as s:
        typer.echo(f"${spend_usd(s, run_id):.2f}")


if __name__ == "__main__":
    app()
