from app.clients.fakes import FakeWebScraper
from app.models.business import Business, BusinessStatus, Segment
from app.pipeline.scrape_site import ScrapeSiteStage


def test_scrapes_up_to_n_per_segment_not_top_n_overall(session):
    """ADR-022: ranking by score alone would concentrate every scrape in one
    segment and make the ICP question unanswerable."""
    for seg in [Segment.EMERGING, Segment.GROWTH,
                Segment.ESTABLISHED, Segment.ENTERPRISE]:
        for i in range(10):
            session.add(Business(cid=f"{seg}-{i}", name=f"{seg}{i}",
                                 segment=seg, website="https://example.com",
                                 status=BusinessStatus.DISCOVERED))
    session.commit()

    scraper = FakeWebScraper()
    ScrapeSiteStage(scraper, per_segment=3).run(session, run_id=None)

    scraped = session.query(Business).filter_by(
        status=BusinessStatus.SITE_SCRAPED).all()
    assert len(scraped) == 12
    for seg in [Segment.EMERGING, Segment.GROWTH,
                Segment.ESTABLISHED, Segment.ENTERPRISE]:
        assert sum(1 for b in scraped if b.segment is seg) == 3


def test_dead_site_advances_with_website_status_dead_not_failed(session):
    """A dead domain is data, not a failure (spec section 10, kind 2)."""
    class DeadScraper:
        def scrape(self, url):
            from app.clients.protocols import ScrapeResult
            return ScrapeResult(url=url, status="dead", raw={})

    session.add(Business(cid="d1", name="Dead", segment=Segment.GROWTH,
                         website="https://gone.example",
                         status=BusinessStatus.DISCOVERED))
    session.commit()

    ScrapeSiteStage(DeadScraper(), per_segment=5).run(session, run_id=None)

    b = session.query(Business).filter_by(cid="d1").one()
    assert b.status is BusinessStatus.SITE_SCRAPED
    assert b.failed_stage is None
