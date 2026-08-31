import structlog
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.requests import Request

from app.api.deps import require_api_key

log = structlog.get_logger()


def create_app() -> FastAPI:
    """Build the FastAPI app.

    A factory rather than a module-level singleton so tests can construct a
    fresh app with its own dependency overrides.
    """
    app = FastAPI(title="Lead Generation API", version="1.0.0")

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
