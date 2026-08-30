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


def test_oversubscribed_segment_is_not_ordered_by_review_count(session):
    """Finding 5 / ADR-022: ratingCount (`review_count`) is a segment label
    only, never a filter. In an oversubscribed segment, ordering candidates
    by review_count before applying the per-segment cap would silently make
    review_count the deciding factor for who gets scraped. Discovery order
    (id) must decide instead."""
    for i in range(5):
        session.add(Business(cid=f"g{i}", name=f"g{i}", segment=Segment.GROWTH,
                             website="https://example.com",
                             review_count=i,     # ascending: g4 has the most
                             status=BusinessStatus.DISCOVERED))
    session.commit()

    scraper = FakeWebScraper()
    ScrapeSiteStage(scraper, per_segment=3).run(session, run_id=None)

    scraped_cids = {b.cid for b in session.query(Business).filter_by(
        status=BusinessStatus.SITE_SCRAPED).all()}
    # Discovery order (id) picks the first 3 created: g0, g1, g2.
    # review_count-desc ordering would instead pick g4, g3, g2.
    assert scraped_cids == {"g0", "g1", "g2"}


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
