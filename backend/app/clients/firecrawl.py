from firecrawl import Firecrawl
from app.clients.protocols import ScrapeResult
from app.core.config import get_settings

PAGE_ALLOWLIST = ("/about", "/contact", "/services", "/team")


class FirecrawlScraper:
    def __init__(self, client: Firecrawl | None = None) -> None:
        self._client = client or Firecrawl(api_key=get_settings().firecrawl_key)

    def scrape(self, url: str) -> ScrapeResult:
        try:
            doc = self._client.scrape(
                url,
                formats=["markdown", "rawHtml", "links"],
                only_main_content=False,   # MUST be False — footers hold contact
                                           # details and vendor badges (ADR-012)
                timeout=30000,
            )
        except Exception:
            return ScrapeResult(url=url, status="dead", raw={})

        data = doc if isinstance(doc, dict) else doc.__dict__
        return ScrapeResult(
            url=url,
            markdown=data.get("markdown"),
            raw_html=data.get("raw_html") or data.get("rawHtml"),
            links=data.get("links", []) or [],
            status="ok",
            raw=data,
        )
