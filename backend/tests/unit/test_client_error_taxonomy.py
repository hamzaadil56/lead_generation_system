"""C1/C2: the client adapters must speak the four-way error taxonomy.

`classify_http_error` and `app/core/errors.py` existed from day one but no
production code path ever raised any of the three classes, so the tenacity
retry, the circuit breaker and the advance-anyway path in
`app/pipeline/base.py` were all dead code. These tests pin the seam
between a provider SDK's exception and the taxonomy class it must become.
"""
import os

os.environ.setdefault("DATABASE_URL",
                      "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test")
os.environ.setdefault("SERPER_KEY", "test-serper-key")
os.environ.setdefault("FIRECRAWL_KEY", "test-firecrawl-key")

import httpx
import pytest
from firecrawl.v2.utils.error_handler import FirecrawlError

from app.clients.firecrawl import FirecrawlScraper
from app.clients.serper import SerperClient
from app.core.errors import (
    BusinessPermanentError,
    RunPermanentError,
    TransientError,
)


class _ExplodingFirecrawl:
    """Stands in for the real SDK client, which raises `FirecrawlError`
    subclasses carrying the API's own status code."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    def scrape(self, url, **kwargs):
        self.calls += 1
        raise self._exc


@pytest.mark.parametrize("status,expected", [
    (402, RunPermanentError),        # out of credits — abort the run
    (401, RunPermanentError),        # expired key
    (403, RunPermanentError),
    (429, TransientError),           # rate limited — back off and retry
    (500, TransientError),
    (502, TransientError),
    (404, BusinessPermanentError),   # this URL is gone — data, not failure
])
def test_firecrawl_api_errors_become_the_right_taxonomy_class(status, expected):
    """The defect: a bare `except Exception` turned every one of these into
    `ScrapeResult(status="dead")`, fabricating a dead-site payload for a
    business whose website was never even looked at."""
    scraper = FirecrawlScraper(
        client=_ExplodingFirecrawl(FirecrawlError("boom", status)))
    with pytest.raises(expected):
        scraper.scrape("https://example.com")


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_firecrawl_provider_failure_is_never_recorded_as_a_dead_site(status):
    """An auth or quota failure must NOT become 'this business has no
    website'. That claim is written to `raw_payloads`, which ADR-003
    forbids deleting, and the business leaves DISCOVERED so `scrape` will
    never retry it."""
    scraper = FirecrawlScraper(
        client=_ExplodingFirecrawl(FirecrawlError("boom", status)))
    with pytest.raises(Exception) as caught:
        scraper.scrape("https://example.com")
    assert not isinstance(caught.value, BusinessPermanentError)


def test_firecrawl_target_site_that_cannot_be_fetched_is_still_a_dead_site():
    """The one row of the spec's error table the old code got right: a
    non-200 from the *target site* is `website_status='dead'`."""
    scraper = FirecrawlScraper(client=_ExplodingFirecrawl(
        Exception("This website is no longer supported")))
    result = scraper.scrape("https://gone.example")
    assert result.status == "dead"
    assert result.raw_html is None


def test_firecrawl_reports_a_dead_site_when_the_target_returns_non_200():
    class Client:
        def scrape(self, url, **kwargs):
            return {"markdown": None, "rawHtml": None, "links": [],
                    "metadata": {"statusCode": 404}}

    result = FirecrawlScraper(client=Client()).scrape("https://gone.example")
    assert result.status == "dead"
    assert result.status_code == 404


def _serper(handler) -> SerperClient:
    return SerperClient(client=httpx.Client(
        transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("status,expected", [
    (429, TransientError),
    (500, TransientError),
    (401, RunPermanentError),
    (402, RunPermanentError),
    (404, BusinessPermanentError),
])
def test_serper_http_errors_become_the_right_taxonomy_class(status, expected):
    """The defect: `resp.raise_for_status()` propagated a raw
    `httpx.HTTPStatusError`, which is not a `TransientError`, so tenacity
    passed it straight through and one 429 killed the whole run."""
    client = _serper(lambda request: httpx.Response(status, json={}))
    with pytest.raises(expected):
        client.search("hvac houston")


def test_serper_transport_failure_is_transient_not_business_data():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(TransientError):
        _serper(handler).search("hvac houston")


def test_website_not_supported_is_about_the_target_site_not_the_account():
    """Confirmed concern from the previous wave. Firecrawl raises its 403
    as `WebsiteNotSupportedError` -- bot protection or robots.txt on the
    TARGET site, not a problem with our key. Routing it through
    `classify_http_error` made it a RunPermanentError, so five
    bot-protected sites in a row would trip the circuit breaker and kill a
    healthy run. `classify_http_error` and the taxonomy are unchanged; only
    this adapter's mapping is."""
    from firecrawl.v2.utils.error_handler import WebsiteNotSupportedError
    scraper = FirecrawlScraper(
        client=_ExplodingFirecrawl(WebsiteNotSupportedError("blocked", 403)))
    with pytest.raises(BusinessPermanentError):
        scraper.scrape("https://bot-protected.example")


def test_firecrawl_request_timeout_is_transient():
    """408 fell through to BusinessPermanentError, so a timeout was
    recorded as a fact about the business instead of being retried."""
    from firecrawl.v2.utils.error_handler import RequestTimeoutError
    scraper = FirecrawlScraper(
        client=_ExplodingFirecrawl(RequestTimeoutError("timed out", 408)))
    with pytest.raises(TransientError):
        scraper.scrape("https://slow.example")
