from datetime import datetime
from pathlib import Path

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
from app.services.budget import spend_usd
from app.services.export import export_leads
from app.services.outcomes import record_outcome
from app.services.rulesets import read_ruleset_definition, read_ruleset_file
from app.services.run_executor import (
    Providers, budget_guard, execute_run)
from app.services.search_plan import build_search_plan

app = typer.Typer()
CONFIG = Path("config")


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
            budget_check=budget_guard(run_id, max_cost))
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
                .run(s, run_id, budget_check=budget_guard(run_id, max_cost)))


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

    Creates the `Run` row, then hands off to `execute_run`, which is the
    same code path the API and the scheduler use. The stage sequence, the
    budget checks between and inside stages, and the terminal-state
    handling all live in `app/services/run_executor.py` so there is exactly
    one implementation of them -- three copies of this control flow is the
    duplication Plan 1's final review flagged.

    The providers are constructed here, from this module's globals, and
    injected: that keeps the CLI in charge of "which adapters" while the
    service stays in charge of "which stages, in what order".
    """
    with get_session() as s:
        run = Run(status="queued", source="cli",
                  search_plan={"vertical": vertical, "state": state,
                               "location": location, "pages": pages},
                  max_cost_usd=max_cost, created_at=datetime.utcnow())
        s.add(run)
        s.commit()
        run_id = run.id

    providers = Providers(search=SerperClient(), scraper=FirecrawlScraper(),
                          reviews=SerpApiReviewProvider())
    result = execute_run(run_id, providers=providers,
                         session_factory=get_session)

    for stage_name, report in result.stages:
        typer.echo(f"{stage_name}: {report}")

    if result.status != "complete":
        # A budget stop or an aborted stage is a failed run, not a quiet
        # success: exiting 0 here once handed the operator a CSV missing
        # 90% of its leads (I3). Non-budget crashes never reach this point
        # -- `execute_run` re-raises them with their traceback intact.
        typer.echo(result.error or "run failed", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"run {run_id} complete")


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
