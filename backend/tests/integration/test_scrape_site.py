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


class _OutOfCreditsScraper:
    """What FirecrawlScraper now raises for an HTTP 402. Previously the
    adapter's bare `except Exception` turned this into
    ScrapeResult(status="dead") for every remaining business."""

    def __init__(self) -> None:
        self.calls = 0

    def scrape(self, url):
        from app.core.errors import RunPermanentError
        self.calls += 1
        raise RunPermanentError("firecrawl: HTTP 402", status_code=402)


def test_firecrawl_running_out_of_credits_trips_the_circuit_breaker(session):
    """C1+C2+I3. Ten businesses, an expired/exhausted key. The breaker must
    stop after 5, no business may be advanced, and no fabricated dead-site
    RawPayload may be written -- `raw_payloads` is append-only (ADR-003),
    so a poisoned row there is unrecoverable through the CLI."""
    from app.models.derived import RawPayload
    for i in range(10):
        session.add(Business(cid=f"x{i}", name=f"x{i}", segment=Segment.GROWTH,
                             website="https://example.com",
                             status=BusinessStatus.DISCOVERED))
    session.commit()

    scraper = _OutOfCreditsScraper()
    report = ScrapeSiteStage(scraper, per_segment=10).run(session, run_id=None)

    assert report.aborted is True
    assert scraper.calls == 5                      # breaker threshold, not 10
    assert session.query(Business).filter_by(
        status=BusinessStatus.SITE_SCRAPED).count() == 0
    assert session.query(RawPayload).filter_by(source="firecrawl").count() == 0


def test_a_failed_firecrawl_call_logs_an_honest_api_call_row(session):
    """C1 (compounding) / I2: scrape_site logged `credits=1,
    status_code=200` unconditionally, including for calls that never
    succeeded. `status_code=200` on a call that 402'd makes `api_calls`
    actively misleading during exactly the incident you would use it to
    diagnose."""
    session.add(Business(cid="p1", name="p1", segment=Segment.GROWTH,
                         website="https://example.com",
                         status=BusinessStatus.DISCOVERED))
    session.commit()

    ScrapeSiteStage(_OutOfCreditsScraper(), per_segment=5).run(session, run_id=None)

    call = session.query(ApiCall).filter_by(provider="firecrawl").one()
    assert call.status_code == 402
    assert call.credits == 0


def test_a_dead_target_site_logs_the_targets_status_code(session):
    class DeadScraper:
        def scrape(self, url):
            from app.clients.protocols import ScrapeResult
            return ScrapeResult(url=url, status="dead", status_code=404, raw={})

    session.add(Business(cid="p2", name="p2", segment=Segment.GROWTH,
                         website="https://gone.example",
                         status=BusinessStatus.DISCOVERED))
    session.commit()

    ScrapeSiteStage(DeadScraper(), per_segment=5).run(session, run_id=None)
    call = session.query(ApiCall).filter_by(provider="firecrawl").one()
    assert call.status_code == 404
    assert call.credits == 1        # Firecrawl bills for the attempt


def test_the_per_segment_cap_is_cumulative_across_runs(session):
    """I6: `select` took up to `per_segment` from the businesses currently
    in DISCOVERED. Scraped businesses leave that status, so the next
    invocation took the NEXT `per_segment` — 20 discovered gave 15 scraped,
    then 4 more on a re-run, and each `run-all` billed another batch.

    The cap exists to hold a bounded stratified sample for testing the open
    ICP hypothesis (ADR-022), so it must bound the sample: businesses in a
    segment that are already past DISCOVERED count toward that segment's
    cap."""
    for i in range(20):
        session.add(Business(cid=f"c{i}", name=f"c{i}", segment=Segment.GROWTH,
                             website="https://example.com",
                             status=BusinessStatus.DISCOVERED))
    session.commit()

    run1, run2, run3 = FakeWebScraper(), FakeWebScraper(), FakeWebScraper()
    ScrapeSiteStage(run1, per_segment=15).run(session, run_id=None)
    ScrapeSiteStage(run2, per_segment=15).run(session, run_id=None)
    ScrapeSiteStage(run3, per_segment=15).run(session, run_id=None)

    assert len(run1.calls) == 15
    assert run2.calls == []          # was 4 — the next batch of leftovers
    assert run3.calls == []


def test_businesses_further_down_the_pipeline_still_count_toward_the_cap(session):
    """The cap must see the whole sample, not just SITE_SCRAPED: a
    business that has already been extracted, scored or failed consumed a
    Firecrawl call too."""
    for i, status in enumerate([BusinessStatus.SCORED,
                                BusinessStatus.SIGNALS_EXTRACTED,
                                BusinessStatus.FAILED]):
        session.add(Business(cid=f"done{i}", name=f"done{i}",
                             segment=Segment.GROWTH,
                             website="https://example.com", status=status))
    for i in range(5):
        session.add(Business(cid=f"new{i}", name=f"new{i}",
                             segment=Segment.GROWTH,
                             website="https://example.com",
                             status=BusinessStatus.DISCOVERED))
    session.commit()

    scraper = FakeWebScraper()
    ScrapeSiteStage(scraper, per_segment=4).run(session, run_id=None)
    assert len(scraper.calls) == 1     # 3 already counted against a cap of 4


class _AlwaysTransientScraper:
    def __init__(self) -> None:
        self.calls = 0

    def scrape(self, url):
        from app.core.errors import TransientError
        self.calls += 1
        raise TransientError("firecrawl: HTTP 429", status_code=429)


def test_a_transient_firecrawl_error_is_actually_retried(session):
    """N1: `_scrape` committed inside the per-business SAVEPOINT to make
    the failed-call api_calls row durable. That commit closed the savepoint
    and expired the ORM, so tenacity's second attempt hit a detached
    `business` and raised a SQLAlchemy error instead of retrying. One 429
    therefore cost exactly ONE provider call, marked the business FAILED
    with a SQLAlchemy message as its error text -- and since the
    per-segment cap is now cumulative, that FAILED row permanently consumes
    a slot in the stratified sample."""
    session.add(Business(cid="t1", name="t1", segment=Segment.GROWTH,
                         website="https://example.com",
                         status=BusinessStatus.DISCOVERED))
    session.commit()

    scraper = _AlwaysTransientScraper()
    report = ScrapeSiteStage(scraper, per_segment=5).run(session, run_id=None)

    assert scraper.calls == 3, "tenacity must make 3 attempts, not 1"
    assert report.failed == 1
    b = session.query(Business).filter_by(cid="t1").one()
    assert b.status is BusinessStatus.FAILED
    # The recorded cause must be the provider's, not SQLAlchemy's.
    assert "429" in b.error_message
    assert "sqlalchemy" not in b.error_message.lower()


def test_the_failed_call_row_stays_durable_across_the_retry_fix(session):
    """Finding 6 must survive N1's fix: the api_calls row for a call that
    really happened is still written, just no longer from inside the
    retry path."""
    session.add(Business(cid="t2", name="t2", segment=Segment.GROWTH,
                         website="https://example.com",
                         status=BusinessStatus.DISCOVERED))
    session.commit()

    ScrapeSiteStage(_AlwaysTransientScraper(), per_segment=5).run(
        session, run_id=None)

    calls = session.query(ApiCall).filter_by(provider="firecrawl").all()
    assert len(calls) == 3          # one honest row per real attempt
    assert all(c.credits == 0 and c.status_code == 429 for c in calls)
