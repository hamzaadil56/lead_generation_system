from datetime import datetime

from app.clients.protocols import WebScraper
from app.domain.sampling import stratify
from app.models.business import Business, BusinessStatus
from app.models.derived import RawPayload, ApiCall
from app.pipeline.base import Stage

PAGE_ALLOWLIST = ("/about", "/contact", "/services", "/team")
MAX_PAGES = 5


class ScrapeSiteStage(Stage):
    name = "scrape_site"
    consumes = BusinessStatus.DISCOVERED
    produces = BusinessStatus.SITE_SCRAPED

    def __init__(self, scraper: WebScraper, per_segment: int = 15) -> None:
        self._scraper = scraper
        self._per_segment = per_segment

    def select(self, session, run_id: int | None, limit: int) -> list[Business]:
        # Ordered by discovery order (id), not review_count: ratingCount is
        # a segment label only, never a filter (ADR-022). Sorting candidates
        # by review_count before applying the per-segment cap would make it
        # the deciding factor for which businesses in an oversubscribed
        # segment ever get scraped — exactly the gate ADR-022 forbids.
        candidates = (session.query(Business)
                      .filter(Business.status == self.consumes,
                              Business.website.isnot(None))
                      .order_by(Business.id)
                      .all())
        return stratify(candidates,
                        key=lambda b: str(b.segment) if b.segment else None,
                        per_group=self._per_segment)

    def process(self, business: Business, session) -> None:
        # select()'s Business.website.isnot(None) filter guarantees this at
        # runtime, but mypy can't see through a SQL filter — narrow here.
        assert business.website is not None
        website = business.website

        home = self._scraper.scrape(website)
        session.add(RawPayload(business_id=business.id, source="firecrawl",
                               url=website,
                               payload=home.model_dump(),
                               raw_text=home.raw_html,
                               fetched_at=datetime.utcnow()))
        session.add(ApiCall(business_id=business.id, provider="firecrawl",
                            endpoint="scrape", credits=1, status_code=200,
                            created_at=datetime.utcnow()))

        if home.status != "ok":
            return      # dead site: advance with reduced coverage, not FAILED

        # Use the returned links rather than guessing paths (ADR-012).
        targets = [
            link for link in home.links
            if any(p in link.lower() for p in PAGE_ALLOWLIST)
        ][: MAX_PAGES - 1]

        for url in targets:
            page = self._scraper.scrape(url)
            session.add(RawPayload(business_id=business.id, source="firecrawl",
                                   url=url, payload=page.model_dump(),
                                   raw_text=page.raw_html,
                                   fetched_at=datetime.utcnow()))
            session.add(ApiCall(business_id=business.id, provider="firecrawl",
                                endpoint="scrape", credits=1, status_code=200,
                                created_at=datetime.utcnow()))
