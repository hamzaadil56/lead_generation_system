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

    `reset_stuck_runs` runs once at startup rather than on a timer: the
    condition it fixes is created by a process dying, so startup is exactly
    when to check.
    """
    from app.scheduler import build_scheduler, reset_stuck_runs

    scheduler = None
    if not app.state.disable_scheduler:
        reset_stuck_runs()
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
