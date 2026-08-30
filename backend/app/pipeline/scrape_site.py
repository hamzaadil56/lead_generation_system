from datetime import datetime

from sqlalchemy import func

from app.clients.protocols import ScrapeResult, WebScraper
from app.core.errors import ProviderError
from app.domain.sampling import stratify
from app.models.business import Business, BusinessStatus
from app.models.derived import RawPayload, ApiCall
from app.pipeline.base import Stage

PAGE_ALLOWLIST = ("/about", "/contact", "/services", "/team")
MAX_PAGES = 5

# Statuses a business can only be in because a scrape was already spent on
# it. FAILED is included: the call was billed regardless of what happened
# afterwards. DISCOVERED and FILTERED_OUT are deliberately absent.
ALREADY_SAMPLED = (
    BusinessStatus.SITE_SCRAPED,
    BusinessStatus.SIGNALS_EXTRACTED,
    BusinessStatus.SCORED,
    BusinessStatus.FAILED,
)


class ScrapeSiteStage(Stage):
    name = "scrape_site"
    consumes = BusinessStatus.DISCOVERED
    produces = BusinessStatus.SITE_SCRAPED

    def __init__(self, scraper: WebScraper, per_segment: int = 15) -> None:
        self._scraper = scraper
        self._per_segment = per_segment

    def _already_sampled(self, session) -> dict[str, int]:
        rows = (session.query(Business.segment, func.count(Business.id))
                .filter(Business.status.in_(ALREADY_SAMPLED),
                        Business.website.isnot(None))
                .group_by(Business.segment).all())
        return {str(segment): count for segment, count in rows
                if segment is not None}

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
        # The cap bounds the SAMPLE, not the batch: businesses in a segment
        # that are already past DISCOVERED count against that segment's
        # cap. Per-invocation semantics made Firecrawl spend unbounded in
        # how many times anyone typed `run-all`, and produced a
        # 60-per-segment sample where ADR-022's experiment specifies ~15.
        return stratify(candidates,
                        key=lambda b: str(b.segment) if b.segment else None,
                        per_group=self._per_segment,
                        already_taken=self._already_sampled(session))

    def _scrape(self, url: str, business_id: int, session) -> ScrapeResult:
        """Scrape one URL and log exactly one honest `api_calls` row.

        The old code logged `credits=1, status_code=200` unconditionally,
        including for calls that never succeeded -- so during the incident
        you would use `api_calls` to diagnose, it says every 402 was a
        successful, billed 200 (C1's compounding note / I2).
        """
        try:
            result = self._scraper.scrape(url)
        except ProviderError as exc:
            session.add(ApiCall(run_id=self._run_id, business_id=business_id,
                                provider="firecrawl", endpoint="scrape",
                                credits=0, status_code=exc.status_code,
                                created_at=datetime.utcnow()))
            session.commit()
            raise

        session.add(ApiCall(run_id=self._run_id, business_id=business_id,
                            provider="firecrawl", endpoint="scrape",
                            # Firecrawl bills the attempt even when the
                            # target site is dead.
                            credits=1, status_code=result.status_code or 200,
                            created_at=datetime.utcnow()))
        return result

    def process(self, business: Business, session) -> None:
        # select()'s Business.website.isnot(None) filter guarantees this at
        # runtime, but mypy can't see through a SQL filter — narrow here.
        assert business.website is not None
        website = business.website

        home = self._scrape(website, business.id, session)
        session.add(RawPayload(business_id=business.id, source="firecrawl",
                               url=website,
                               payload=home.model_dump(),
                               raw_text=home.raw_html,
                               fetched_at=datetime.utcnow()))

        if home.status != "ok":
            return      # dead site: advance with reduced coverage, not FAILED

        # Use the returned links rather than guessing paths (ADR-012).
        targets = [
            link for link in home.links
            if any(p in link.lower() for p in PAGE_ALLOWLIST)
        ][: MAX_PAGES - 1]

        for url in targets:
            page = self._scrape(url, business.id, session)
            session.add(RawPayload(business_id=business.id, source="firecrawl",
                                   url=url, payload=page.model_dump(),
                                   raw_text=page.raw_html,
                                   fetched_at=datetime.utcnow()))
