from datetime import datetime, timedelta, UTC
from app.clients.protocols import ReviewRecord
from app.clients.fakes import FakeReviewProvider
from app.models.business import Business, BusinessStatus, Segment
from app.models.derived import Score, Review
from app.pipeline.fetch_reviews import FetchReviewsStage


def _recent(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _scored(session, cid: str, fit: int) -> Business:
    b = Business(cid=cid, name=cid, segment=Segment.GROWTH,
                 status=BusinessStatus.SCORED)
    session.add(b); session.flush()
    session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                      fit_score=fit, pain_score=50, quadrant="nurture",
                      coverage=0.6, reasons=[]))
    session.commit()
    return b


def test_enriches_only_the_top_n_by_fit_score(session):
    for i in range(10):
        _scored(session, f"c{i}", fit=i * 10)

    provider = FakeReviewProvider([ReviewRecord(iso_date=_recent(5),
                                                snippet="nobody answered")])
    FetchReviewsStage(provider, top_n=3).run(session, run_id=None)

    assert len(provider.calls) == 3
    enriched = session.query(Business).filter_by(
        status=BusinessStatus.SITE_SCRAPED).all()
    assert {b.cid for b in enriched} == {"c9", "c8", "c7"}


def test_resets_status_so_signals_and_score_rerun(session):
    """The enrichment loop from ADR-020 — no new machinery, just a status
    reset back to a stage input."""
    b = _scored(session, "c1", fit=90)
    FetchReviewsStage(FakeReviewProvider([]), top_n=1).run(session, run_id=None)
    assert session.query(Business).filter_by(cid="c1").one().status \
        is BusinessStatus.SITE_SCRAPED


def test_does_not_re_enrich_a_business_that_already_has_reviews(session):
    b = _scored(session, "c1", fit=90)
    session.add(Review(business_id=b.id, rating=5, published_at=datetime.now(UTC),
                       text="ok", source="serpapi"))
    session.commit()

    provider = FakeReviewProvider([])
    FetchReviewsStage(provider, top_n=5).run(session, run_id=None)
    assert provider.calls == []


def test_monthly_ceiling_stops_the_stage(session):
    """The free tier resets monthly and does not roll over; exceeding it
    silently degrades later runs to basic tier (ADR-020)."""
    for i in range(5):
        _scored(session, f"c{i}", fit=i * 10)
    provider = FakeReviewProvider([])
    report = FetchReviewsStage(provider, top_n=5,
                               monthly_ceiling=4).run(session, run_id=None)
    assert len(provider.calls) <= 2      # 2 calls/business against a 4 ceiling
    assert report.reason is not None
