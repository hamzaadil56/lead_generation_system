from datetime import datetime
from pathlib import Path

import typer
import yaml

from app.clients.firecrawl import FirecrawlScraper
from app.clients.serpapi_reviews import SerpApiReviewProvider
from app.clients.serper import SerperClient
from app.core.config import get_settings
from app.core.db import get_session
from app.domain.email import normalize_email
from app.models.manual import Suppression
from app.models.run import Run
from app.pipeline.base import StageReport
from app.pipeline.discover import DiscoverStage
from app.pipeline.extract_signals import ExtractSignalsStage
from app.pipeline.fetch_reviews import FetchReviewsStage
from app.pipeline.score import ScoreStage
from app.pipeline.scrape_site import ScrapeSiteStage
from app.repositories.leads import LeadFilters
from app.scheduler import reset_stuck_runs
from app.services.budget import spend_usd
from app.services.contact_export import export_contacts
from app.services.contact_harvest import harvest_for_filters
from app.services.export import export_leads
from app.services.outcomes import record_outcome
from app.services.rulesets import read_ruleset_definition, read_ruleset_file
from app.services.run_executor import (
    Providers, budget_guard, execute_run)
from app.services.search_plan import build_search_plan
from app.services.seed import seed_demo

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
    # Built BEFORE the Run row, deliberately. These constructors can raise
    # (an empty FIRECRAWL_KEY passes pydantic, then `Firecrawl(api_key="")`
    # raises), and the row below is created `running`: a raise after it
    # would strand a run at `running` with no `finished_at` forever, the
    # one outcome `execute_run` is built to prevent. Constructing first
    # means a bad key produces no row at all, and no terminal-state
    # handling has to exist outside `run_executor`.
    providers = Providers(search=SerperClient(), scraper=FirecrawlScraper(),
                          reviews=SerpApiReviewProvider())

    with get_session() as s:
        # Created `running`, with `started_at`, in the SAME transaction --
        # never `queued`. The CLI executes the run itself moments later,
        # but the API container's poller filters on `status == "queued"`,
        # so a row committed as `queued` was claimable during the whole
        # gap between this commit and `execute_run` below -- which used to
        # include constructing three provider clients (now done above).
        # ADR-017 and the Dockerfile
        # document the CLI as a second entrypoint into the same image and
        # database, so that poller is a real process: it would walk all
        # seven stages against this same run_id concurrently -- duplicated
        # Serper and Firecrawl spend and two writers on the same business
        # rows. `execute_run` cannot refuse `running` (that would deadlock
        # the poller on runs it just claimed), so the fix has to be here:
        # the row is never visible to the claim query at all.
        now = datetime.utcnow()
        run = Run(status="running", source="cli",
                  search_plan={"vertical": vertical, "state": state,
                               "location": location, "pages": pages},
                  max_cost_usd=max_cost, created_at=now, started_at=now)
        s.add(run)
        s.commit()
        run_id = run.id

    def echo_stage(stage_name: str, report: StageReport) -> None:
        """Stream each stage's outcome as it lands.

        Printing from a `result.stages` loop after `execute_run` returned
        buffered the whole run's feedback -- and lost it completely when a
        stage crashed and the exception was re-raised, which is exactly
        when the operator needs to know which stages got through. The
        service never prints; it calls back, so the API and the scheduler
        can do something else with the same events.
        """
        typer.echo(f"{stage_name}: {report}")

    result = execute_run(run_id, providers=providers,
                         session_factory=get_session, on_stage=echo_stage)

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
def suppress(email: str, reason: str = "unsubscribed") -> None:
    """Never email this address again.

    Without this command the suppressions table can never hold a row and the
    export's third predicate is dead code. Normalised through the same
    function the harvester uses, and upserted on the primary key, so
    suppressing twice is not an error.
    """
    valid = {"unsubscribed", "bounced", "complained", "manual"}
    if reason not in valid:
        raise typer.BadParameter(f"reason must be one of {sorted(valid)}")
    address = normalize_email(email)
    if address is None:
        raise typer.BadParameter(f"not a valid email: {email}")
    with get_session() as s:
        row = s.get(Suppression, address)
        if row is None:
            s.add(Suppression(email=address, reason=reason, source="cli",
                              created_at=datetime.utcnow()))
        else:
            row.reason = reason
        s.commit()
        typer.echo(f"suppressed {address} ({reason})")


@app.command("harvest-contacts")
def harvest_contacts_cmd(quadrant: str | None = None, min_fit: int = 0,
                         vertical: str = "hvac") -> None:
    """Harvest addresses from cached HTML. Free -- calls no provider."""
    version = _ruleset(vertical).version
    with get_session() as s:
        result = harvest_for_filters(s, LeadFilters(
            quadrant=quadrant, min_fit=min_fit, ruleset_version=version))
        typer.echo(f"harvested {result.created} contacts "
                   f"across {result.businesses} businesses")


@app.command("export-contacts")
def export_contacts_cmd(out: Path = Path("contacts.csv"),
                        quadrant: str | None = None, min_fit: int = 0,
                        vertical: str = "hvac") -> None:
    # `ruleset_version` is threaded through explicitly rather than
    # hardcoded: the leads export shipped hardcoded to "hvac_v1" and a
    # second vertical exported zero rows -- a failure that reads as "no
    # leads matched" rather than as a bug.
    version = _ruleset(vertical).version
    with get_session() as s:
        count = export_contacts(s, LeadFilters(
            quadrant=quadrant, min_fit=min_fit, ruleset_version=version), out)
        typer.echo(f"exported {count} contacts -> {out}")


@app.command()
def outcome(cid: str, status: str, notes: str | None = None) -> None:
    # Record what happened: new|contacted|replied|booked|won|lost
    with get_session() as s:
        record_outcome(s, cid, status, notes)
        typer.echo(f"{cid} -> {status}")


@app.command("reset-stuck-runs")
def reset_stuck_runs_cmd(
        older_than_hours: int = typer.Option(
            6, "--older-than-hours", min=0,
            help="Requeue runs that have been `running` longer than this. "
                 "Only use a value you are sure exceeds any run still "
                 "executing in another process.")) -> None:
    """Requeue runs stranded at `running` by a process that died mid-run.

    Deliberately manual. Nothing reconciles runs automatically -- not the
    scheduler, not app startup. A run marked `running` is either abandoned
    or in flight, and the schema cannot tell the two apart: `started_at` is
    stamped once and never refreshed, and there is no heartbeat or owner
    column. Requeuing a live run makes the poller re-claim it and re-bill
    all seven stages against the same run_id, so every automatic cutoff is
    a guess about whether another process is alive. An operator running
    this knows which runs are actually executing; a timer never does.
    """
    count = reset_stuck_runs(max_age_hours=older_than_hours)
    typer.echo(f"requeued {count} run(s) stuck running for more than "
               f"{older_than_hours}h")


@app.command()
def spend(run_id: int | None = None) -> None:
    with get_session() as s:
        typer.echo(f"${spend_usd(s, run_id):.2f}")


@app.command("seed-demo")
def seed_demo_cmd() -> None:
    """Insert a fixed demo dataset for end-to-end tests and local demos.

    Idempotent. Intended for a throwaway database -- never run it against
    one holding real run data.
    """
    with get_session() as s:
        counts = seed_demo(s)
    typer.echo(f"seeded: {counts}")


if __name__ == "__main__":
    app()
