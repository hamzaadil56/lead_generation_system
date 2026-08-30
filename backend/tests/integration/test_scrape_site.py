from app.clients.fakes import FakeWebScraper
from app.models.business import Business, BusinessStatus, Segment
from app.models.derived import ApiCall
from app.models.run import Run
from app.pipeline.scrape_site import ScrapeSiteStage
from app.services.budget import spend_usd


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


def test_api_calls_carry_the_run_id_so_spend_usd_sees_per_run_firecrawl_cost(session):
    """Correction B: process() is never passed run_id, so scrape_site must
    read it off self._run_id (set by Stage.run before the selection loop).
    Without this, ApiCall rows for scrape_site are orphaned (run_id=None)
    and a per-run spend_usd(session, run_id) query silently misses all
    Firecrawl spend."""
    run = Run(status="running", source="cli", search_plan={})
    session.add(run)
    session.commit()

    session.add(Business(cid="r1", name="r1", segment=Segment.GROWTH,
                         website="https://example.com",
                         status=BusinessStatus.DISCOVERED))
    session.commit()

    ScrapeSiteStage(FakeWebScraper(), per_segment=5).run(session, run_id=run.id)

    calls = session.query(ApiCall).filter_by(provider="firecrawl").all()
    assert len(calls) > 0
    assert all(c.run_id == run.id for c in calls)
    assert spend_usd(session, run_id=run.id) > 0
    # A different/absent run_id must see none of this spend.
    assert spend_usd(session, run_id=run.id + 1) == 0.0
