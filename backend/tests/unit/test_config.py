import pytest
from pydantic import ValidationError
from app.core.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("SERPER_KEY", "sk-serper")
    monkeypatch.setenv("FIRECRAWL_KEY", "fc-key")
    s = Settings()
    assert s.serper_key == "sk-serper"
    assert s.enrichment_top_n == 25
    assert s.stratified_per_segment == 15
    assert s.serpapi_key is None


def test_settings_fails_fast_when_required_var_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SERPER_KEY", "sk-serper")
    monkeypatch.setenv("FIRECRAWL_KEY", "fc-key")
    with pytest.raises(ValidationError):
        Settings()
