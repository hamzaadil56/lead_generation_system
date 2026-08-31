from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.requests import Request

from app.api.deps import require_api_key
from app.core.errors import SearchPlanError

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the scheduler with the app; stop it cleanly on shutdown.

    Startup deliberately does NOT reconcile stuck runs, and neither does
    any timer. Both have been tried and both are unsafe here; read this
    before adding either back.

    `reset_stuck_runs` flips a run from `running` to `queued`. If that run
    is still executing somewhere, the poller re-claims it and a second
    process walks all seven stages against the same run_id -- duplicated
    Serper and Firecrawl spend, two writers on the same business rows, and
    whichever finishes second overwrites the terminal state. `execute_run`
    cannot defend against this: it deliberately allows `running`, because
    refusing it would deadlock the poller that just claimed the run.

    A timed job cannot tell *abandoned by a dead process* from *still
    executing*: `started_at` is stamped once and never refreshed, and
    there is no heartbeat or owner column (that would be DDL).

    A startup call was kept for one round on the argument that a freshly
    started process owns no in-flight runs. That argument is false in this
    deployment: ADR-017 and the Dockerfile document the CLI as a second
    entrypoint into the same image and database, so this container can be
    restarting (deploy, crash, OOM, `docker compose restart`) while a CLI
    run is minutes into its scrape stage. A cutoff of 0 requeues it; any
    other cutoff is still a guess about whether another process is alive.

    So reconciliation is an operator action, not a timer:

        docker compose run --rm api python -m cli reset-stuck-runs

    A human running that knows what is currently executing. Everything a
    live process can do to strand its own run is already closed inside
    `execute_run`, which writes terminal state before re-raising on every
    path it can raise from; only a process that dies mid-run leaves a
    stranded row, and that is exactly the case an operator can identify.
    """
    from app.scheduler import build_scheduler

    scheduler = None
    if not app.state.disable_scheduler:
        scheduler = build_scheduler()
        scheduler.start()
        log.info("scheduler.started")
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")


def create_app(*, disable_scheduler: bool = False) -> FastAPI:
    """Build the FastAPI app.

    A factory rather than a module-level singleton so tests can construct a
    fresh app with its own dependency overrides.

    `disable_scheduler` exists for the test suite: a background scheduler
    started inside the tests would claim queued runs and execute them
    against the real, paid providers.
    """
    app = FastAPI(title="Lead Generation API", version="1.0.0",
                  lifespan=lifespan)
    app.state.disable_scheduler = disable_scheduler

    @app.get("/health")
    def health() -> dict[str, str]:
        """Unauthenticated on purpose: the container healthcheck calls it."""
        return {"status": "ok"}

    @app.exception_handler(SearchPlanError)
    def search_plan_error_handler(request: Request,
                                  exc: SearchPlanError) -> JSONResponse:
        """An unknown vertical or state reaches the router as a
        `SearchPlanError` from `build_search_plan`. That is a client
        mistake, and its message is written by us, so it is safe to echo.

        Registered for `SearchPlanError` and NOT for `ValueError`.
        `pydantic.ValidationError` subclasses `ValueError`, so the broad
        handler this replaces turned every server-side DTO construction
        failure inside a router into a 400 -- a client error -- carrying
        the raw pydantic message: internal field names, type errors, and
        truncated input values. It is what let a broken response schema
        (`ReasonOut` vs `Score.reasons`) read as "the client asked wrong"
        for two review rounds, and it hid the failure from any monitoring
        rule watching 5xx. Anything not named here is a 500, deliberately.

        FastAPI's own request-validation path is untouched: a malformed
        request body is still a 422 raised as `RequestValidationError`,
        which never reaches this handler.
        """
        log.warning("api.bad_request", path=request.url.path, error=str(exc))
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    from app.api.routers import leads, meta, runs
    for router in (runs.router, leads.router, meta.router):
        app.include_router(router, dependencies=[Depends(require_api_key)])

    return app


app = create_app()
