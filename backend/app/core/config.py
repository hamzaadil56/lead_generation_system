from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    serper_key: str
    firecrawl_key: str
    serpapi_key: str | None = None
    sentry_dsn: str | None = None
    # Shared secret the Next.js server presents as X-API-Key. Optional so the
    # CLI and the test suite keep working without it; when unset, every
    # protected route returns 401 rather than silently allowing access.
    api_key: str | None = None

    # Ceiling applied to an API-created run whose body omits
    # `max_cost_usd` (the common case). Without it, `POST /runs` queued an
    # unbounded run: before this branch spending required a human at a
    # terminal, and the HTTP path removes that, so a UI retry loop or a
    # stuck poll could queue runs nobody is watching. $5 is several times
    # the worst measured single run (an hvac/TX plan at 20 pages prices at
    # ~$1.44 of Serper plus ~$0.12 of Firecrawl), so it does not clip a
    # legitimate run. This is a per-run default only -- there is
    # deliberately no global or monthly cap here. An explicit
    # `max_cost_usd` in the request always wins, and the CLI is unaffected
    # (a human chose to type the command).
    default_run_max_cost_usd: float = 5.0

    enrichment_top_n: int = 25
    stratified_per_segment: int = 15
    serpapi_monthly_ceiling: int = 250


@lru_cache
def get_settings() -> Settings:
    return Settings()
