from pathlib import Path

import typer
import yaml

from app.clients.firecrawl import FirecrawlScraper
from app.clients.serpapi_reviews import SerpApiReviewProvider
from app.clients.serper import SerperClient
from app.core.config import get_settings
from app.core.db import get_session
from app.pipeline.discover import DiscoverStage
from app.pipeline.extract_signals import ExtractSignalsStage
from app.pipeline.fetch_reviews import FetchReviewsStage
from app.pipeline.score import ScoreStage
from app.pipeline.scrape_site import ScrapeSiteStage
from app.services.budget import spend_usd
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
             pages: int = 5) -> None:
    with get_session() as s:
        report = DiscoverStage(SerperClient()).discover(
            s, None, _plan(vertical, state, location, pages))
        typer.echo(f"discovered: {report.processed}")


@app.command()
def scrape(per_segment: int | None = None) -> None:
    n = per_segment or get_settings().stratified_per_segment
    with get_session() as s:
        typer.echo(ScrapeSiteStage(FirecrawlScraper(), per_segment=n)
                   .run(s, None))


@app.command()
def extract() -> None:
    with get_session() as s:
        typer.echo(ExtractSignalsStage().run(s, None))


@app.command()
def score(vertical: str = "hvac") -> None:
    with get_session() as s:
        typer.echo(ScoreStage(_ruleset(vertical)).run(s, None))


@app.command()
def enrich(top_n: int | None = None) -> None:
    settings = get_settings()
    with get_session() as s:
        typer.echo(FetchReviewsStage(
            SerpApiReviewProvider(), top_n=top_n or settings.enrichment_top_n,
            monthly_ceiling=settings.serpapi_monthly_ceiling).run(s, None))


@app.command("run-all")
def run_all(vertical: str, state: str | None = None, location: str | None = None,
            pages: int = 5) -> None:
    """Discover -> scrape -> extract -> score -> enrich -> extract -> score."""
    discover(vertical, state, location, pages)
    scrape()
    extract()
    score(vertical)
    enrich()
    extract()      # the ADR-020 loop: re-derive over the richer data
    score(vertical)


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
