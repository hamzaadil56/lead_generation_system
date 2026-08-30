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
from app.services.rulesets import read_ruleset_file
from app.services.search_plan import build_search_plan

app = typer.Typer()
CONFIG = Path("config")


def _plan(vertical: str, state: str | None, location: str | None, pages: int):
    return build_search_plan(
        vertical, state, location,
        yaml.safe_load((CONFIG / "verticals.yaml").read_text()),
        yaml.safe_load((CONFIG / "locations.yaml").read_text()),
        pages_per_query=pages,
    )


def _ruleset(vertical: str):
    cfg = yaml.safe_load((CONFIG / "verticals.yaml").read_text())
    return read_ruleset_file(CONFIG / "rulesets" / f"{cfg[vertical]['ruleset']}.yaml")


@app.command()
def discover(vertical: str, state: str | None = None, location: str | None = None,
             pages: int = 5, run_id: int | None = None) -> None:
    with get_session() as s:
        report = DiscoverStage(SerperClient()).discover(
            s, run_id, _plan(vertical, state, location, pages))
        typer.echo(f"discovered: {report.processed}")


@app.command()
def scrape(per_segment: int | None = None, run_id: int | None = None) -> None:
    n = per_segment or get_settings().stratified_per_segment
    with get_session() as s:
        typer.echo(ScrapeSiteStage(FirecrawlScraper(), per_segment=n)
                   .run(s, run_id))


@app.command()
def extract(run_id: int | None = None) -> None:
    with get_session() as s:
        typer.echo(ExtractSignalsStage().run(s, run_id))


@app.command()
def score(vertical: str = "hvac", run_id: int | None = None) -> None:
    with get_session() as s:
        typer.echo(ScoreStage(_ruleset(vertical)).run(s, run_id))


@app.command()
def enrich(top_n: int | None = None, run_id: int | None = None) -> None:
    settings = get_settings()
    with get_session() as s:
        typer.echo(FetchReviewsStage(
            SerpApiReviewProvider(), top_n=top_n or settings.enrichment_top_n,
            monthly_ceiling=settings.serpapi_monthly_ceiling).run(s, run_id))


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
    checked BEFORE each stage — so the run stops before spending more,
    rather than after it has already overspent.
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
        ("discover", lambda: discover(vertical, state, location, pages, run_id=run_id)),
        ("scrape", lambda: scrape(run_id=run_id)),
        ("extract", lambda: extract(run_id=run_id)),
        ("score", lambda: score(vertical, run_id=run_id)),
        ("enrich", lambda: enrich(run_id=run_id)),
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
        run_stage()

    with get_session() as s:
        run_row = s.query(Run).filter_by(id=run_id).one()
        run_row.status = "complete"
        run_row.finished_at = datetime.utcnow()
        run_row.actual_cost = spend_usd(s, run_id)
        s.commit()


@app.command("export")
def export_cmd(out: Path = Path("leads.csv"), quadrant: str | None = None,
               min_fit: int = 0) -> None:
    with get_session() as s:
        typer.echo(f"exported {export_leads(s, quadrant, min_fit, out)} -> {out}")


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
