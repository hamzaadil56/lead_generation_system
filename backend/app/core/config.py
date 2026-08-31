from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    serper_key: str
    firecrawl_key: str
    serpapi_key: str | None = None
    sentry_dsn: str | None = None

    enrichment_top_n: int = 25
    stratified_per_segment: int = 15
    serpapi_monthly_ceiling: int = 250


@lru_cache
def get_settings() -> Settings:
    return Settings()
