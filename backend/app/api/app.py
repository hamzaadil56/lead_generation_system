from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.requests import Request

from app.api.deps import require_api_key

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the scheduler with the app; stop it cleanly on shutdown.

    This startup call is the ONLY place stuck runs are reconciled, and that
    is deliberate. Do not add a timed `reset_stuck_runs` job -- one was
    added and removed. A timer cannot tell a run abandoned by a dead
    process from one still executing in this process (`started_at` is
    stamped once and never refreshed, and there is no heartbeat column;
    that would be DDL). It therefore requeues live runs mid-flight, and the
    next 30-second poll re-claims and concurrently re-executes the same
    run_id: double billing and two writers on the same rows.

    Startup has no such race -- it runs before the scheduler starts, so no
    run can be in flight -- and it covers the case that actually occurs: a
    process dying mid-run. Every other way a run could be stranded while
    this process stays alive is closed inside `execute_run`, which writes
    terminal state before re-raising on every path it can raise from.

    Hence the cutoff of 0: requeue anything still `running`. That rests on
    an assumption worth naming -- under ADR-010 this is one container with
    one in-process scheduler, so a freshly started process owns no
    in-flight runs and anything left `running` is by definition orphaned by
    the process that died. This is the only place that assumption is
    load-bearing: the claim path is already multi-instance-safe on its own
    (`claim_next_queued_run` uses FOR UPDATE SKIP LOCKED). If a second
    instance is ever deployed, this line -- not a timer -- is what needs
    rethinking, and a heartbeat column is the shape of the answer.
    """
    from app.scheduler import build_scheduler, reset_stuck_runs

    scheduler = None
    if not app.state.disable_scheduler:
        reset_stuck_runs(max_age_hours=0)
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

    @app.exception_handler(ValueError)
    def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        """A bad vertical or state reaches the router as ValueError from
        build_search_plan. That is a client mistake, not a 500."""
        log.warning("api.bad_request", path=request.url.path, error=str(exc))
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    from app.api.routers import leads, meta, runs
    for router in (runs.router, leads.router, meta.router):
        app.include_router(router, dependencies=[Depends(require_api_key)])

    return app


app = create_app()
