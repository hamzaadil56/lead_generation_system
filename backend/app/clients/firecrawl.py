from typing import Any

import requests
from firecrawl import Firecrawl
from firecrawl.v2.utils.error_handler import (
    FirecrawlError,
    RequestTimeoutError,
    WebsiteNotSupportedError,
)

from app.clients.http_errors import raise_for_status_code
from app.clients.protocols import ScrapeResult
from app.core.config import get_settings
from app.core.errors import BusinessPermanentError, TransientError

PAGE_ALLOWLIST = ("/about", "/contact", "/services", "/team")


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    return dict(getattr(obj, "__dict__", {}) or {})


class FirecrawlScraper:
    def __init__(self, client: Firecrawl | None = None) -> None:
        self._client = client or Firecrawl(api_key=get_settings().firecrawl_key)

    def scrape(self, url: str) -> ScrapeResult:
        # Only the provider call is inside the try: a failure here is the
        # provider's, never ours. The previous bare `except Exception`
        # wrapped the whole method and turned an expired key (401), an
        # out-of-credits response (402) and a rate limit (429) into the
        # sentence "this business has no website" -- written permanently to
        # `raw_payloads` and advancing the business out of DISCOVERED, so
        # `scrape` could never retry it (C1).
        try:
            doc = self._client.scrape(
                url,
                formats=["markdown", "rawHtml", "links"],
                only_main_content=False,   # MUST be False — footers hold contact
                                           # details and vendor badges (ADR-012)
                timeout=30000,
            )
        except WebsiteNotSupportedError as exc:
            # Firecrawl returns 403 for a TARGET site it cannot fetch --
            # bot protection, robots.txt -- not for a problem with our
            # account. `classify_http_error` groups 403 with 401/402
            # because that is what it means for every other provider, so
            # the correction belongs here rather than in the taxonomy:
            # five bot-protected sites in a row would otherwise trip the
            # circuit breaker and kill a healthy run.
            raise BusinessPermanentError(f"firecrawl: {exc}",
                                         status_code=403) from exc
        except RequestTimeoutError as exc:
            # 408 fell through to BusinessPermanentError, recording a
            # timeout as a fact about the business instead of retrying it.
            raise TransientError(f"firecrawl: {exc}", status_code=408) from exc
        except FirecrawlError as exc:
            # Firecrawl's OWN API failed. Classify by its status code:
            # 401/402 abort the run, 429/5xx retry, anything else is about
            # this one request.
            raise_for_status_code(getattr(exc, "status_code", None),
                                  "firecrawl", str(exc))
        except requests.RequestException as exc:
            # Never reached the API at all — retryable, and emphatically
            # not evidence about the target website.
            raise TransientError(f"firecrawl: {exc!r}") from exc
        except Exception as exc:
            # What is left is the SDK's `raise Exception(body["error"])` for
            # a successful API call whose *target site* could not be
            # fetched (DNS failure, parked domain, site refuses robots).
            # That is the one row of the spec's error table where
            # `status="dead"` is correct: it is data about the business.
            return ScrapeResult(url=url, status="dead",
                                raw={"error": str(exc)})

        data = _as_dict(doc)
        metadata = _as_dict(data.get("metadata"))
        status_code = metadata.get("statusCode") or metadata.get("status_code")
        if isinstance(status_code, int) and status_code >= 400:
            # Non-200 from the TARGET site (spec section 10, kind 2).
            return ScrapeResult(url=url, status="dead", status_code=status_code,
                                raw=data)

        return ScrapeResult(
            url=url,
            markdown=data.get("markdown"),
            raw_html=data.get("raw_html") or data.get("rawHtml"),
            links=data.get("links", []) or [],
            status="ok",
            status_code=status_code if isinstance(status_code, int) else 200,
            raw=data,
        )
