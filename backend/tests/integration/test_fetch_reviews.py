from datetime import datetime, timedelta, UTC
from app.clients.protocols import ReviewRecord, ReviewResult
from app.clients.fakes import FakeReviewProvider
from app.models.business import Business, BusinessStatus, Segment
from app.models.derived import ApiCall, Score, Review
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


class PagedReviewProvider:
    """A `ReviewProvider` that serves multiple pages, so
    `collect_recent_reviews` makes more than one real call for a single
    business — unlike `FakeReviewProvider`, which never paginates."""

    def __init__(self, pages: list[list[ReviewRecord]]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult:
        idx = len(self.calls)
        self.calls.append(data_id)
        has_next = idx + 1 < len(self.pages)
        return ReviewResult(reviews=self.pages[idx],
                            next_page_token="tok" if has_next else None, raw={})


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
    session.add(ApiCall(business_id=b.id, provider="serpapi",
                        endpoint="google_maps_reviews", credits=1,
                        status_code=200, created_at=datetime.utcnow()))
    session.commit()

    provider = FakeReviewProvider([])
    FetchReviewsStage(provider, top_n=5).run(session, run_id=None)
    assert provider.calls == []


def test_zero_review_business_is_not_reselected_on_a_second_run(session):
    """Finding 2: a business whose SerpApi lookup legitimately returns zero
    recent reviews never gets a `Review` row. It must still be marked
    enriched (via the durable `api_calls` row) so it is not re-billed
    forever once it loops back through extract_signals/score to SCORED."""
    b = _scored(session, "c1", fit=90)
    provider = FakeReviewProvider([])  # always returns zero reviews

    FetchReviewsStage(provider, top_n=5).run(session, run_id=None)
    assert len(provider.calls) == 1
    assert session.query(Business).filter_by(cid="c1").one().status \
        is BusinessStatus.SITE_SCRAPED

    # Simulate the natural loop: extract_signals + score run again over the
    # (still reviewless) business and re-produce SCORED.
    b.status = BusinessStatus.SCORED
    session.commit()

    FetchReviewsStage(provider, top_n=5).run(session, run_id=None)
    assert len(provider.calls) == 1      # not called again — no re-billing


def test_ceiling_counts_credits_not_rows(session):
    """Finding 1: two prior `api_calls` rows already logged 4 credits each
    (8 total, but only 2 rows). A ceiling that counted rows instead of
    summing credits would see spend of 2 and let a new business through;
    summing credits correctly sees spend of 8 and must reserve the
    worst-case 4 more, which trips a ceiling of 10."""
    b = _scored(session, "already", fit=50)
    session.add(ApiCall(business_id=b.id, provider="serpapi",
                        endpoint="google_maps_reviews", credits=4,
                        status_code=200, created_at=datetime.utcnow()))
    session.add(ApiCall(business_id=b.id, provider="serpapi",
                        endpoint="google_maps_reviews", credits=4,
                        status_code=200, created_at=datetime.utcnow()))
    session.commit()
    b.status = BusinessStatus.SCORED   # keep it out of "already enriched"
    session.commit()                   # so it would be eligible if not for spend

    candidate = _scored(session, "new", fit=90)
    provider = FakeReviewProvider([])
    report = FetchReviewsStage(provider, top_n=5,
                               monthly_ceiling=10).run(session, run_id=None)

    assert provider.calls == []
    assert report.reason is not None


def test_logged_credits_equal_actual_number_of_provider_calls(session):
    """Finding 3: the logged `credits` must equal the real number of
    provider calls `collect_recent_reviews` made, not a hardcoded guess —
    checked for both a multi-page and a single-page business."""
    recent = _recent(5)

    b_multi = _scored(session, "multi", fit=90)
    multi_provider = PagedReviewProvider([
        [ReviewRecord(iso_date=recent, snippet="a")],
        [ReviewRecord(iso_date=recent, snippet="b")],
        [ReviewRecord(iso_date=recent, snippet="c")],
    ])
    FetchReviewsStage(multi_provider, top_n=5).run(session, run_id=None)
    assert len(multi_provider.calls) == 3
    multi_call = session.query(ApiCall).filter_by(
        business_id=b_multi.id, provider="serpapi").one()
    assert multi_call.credits == 3

    b_single = _scored(session, "single", fit=90)
    single_provider = PagedReviewProvider([
        [ReviewRecord(iso_date=recent, snippet="a")],
    ])
    FetchReviewsStage(single_provider, top_n=5).run(session, run_id=None)
    assert len(single_provider.calls) == 1
    single_call = session.query(ApiCall).filter_by(
        business_id=b_single.id, provider="serpapi").one()
    assert single_call.credits == 1


def test_monthly_ceiling_stops_the_stage(session):
    """The free tier resets monthly and does not roll over; exceeding it
    silently degrades later runs to basic tier (ADR-020).

    With monthly_ceiling=4 and the worst-case reservation of
    MAX_CALLS_PER_BUSINESS=4: the first business is let through (0 + 4 is
    not > 4), costs 1 real credit (FakeReviewProvider never paginates), so
    spent becomes 1; the second business trips the check (1 + 4 > 4) and
    the stage stops. Exactly 1 business is processed, exactly 1 real call
    is made — pinned exactly, not just bounded, so a regression in the
    reservation arithmetic fails this test."""
    for i in range(5):
        _scored(session, f"c{i}", fit=i * 10)
    provider = FakeReviewProvider([])
    report = FetchReviewsStage(provider, top_n=5,
                               monthly_ceiling=4).run(session, run_id=None)
    assert len(provider.calls) == 1
    assert report.processed == 1
    assert report.reason is not None


def test_serpapi_response_is_persisted_to_raw_payloads(session):
    """C4/ADR-003: `raw_payloads` is the permanent record every other paid
    stage writes, and `derived.py` already lists `serpapi_reviews` as an
    expected source. Without it, `reviews` is not rebuildable from
    anything and the enrichment spend is unrecoverable."""
    from app.models.derived import RawPayload
    _scored(session, "c1", fit=90)
    provider = PagedReviewProvider([
        [ReviewRecord(iso_date=_recent(5), snippet="a")],
        [ReviewRecord(iso_date=_recent(6), snippet="b")],
    ])
    FetchReviewsStage(provider, top_n=1).run(session, run_id=None)

    payloads = session.query(RawPayload).filter_by(
        source="serpapi_reviews").all()
    assert len(payloads) == 2          # one per real provider call
    assert all(p.payload is not None for p in payloads)


def test_signals_survive_the_adr_003_drop_and_rebuild_workflow(session):
    """C4's reproduction. ADR-003 promises that dropping the derived tables
    and re-running the pure stages is free and lossless. It was not: nothing
    could re-derive `missed_call_complaints_90d`, so pain collapsed 45 -> 20
    and the permanent `api_calls` marker meant the business could never be
    re-enriched at any price."""
    from app.models.derived import Signals
    from app.pipeline.extract_signals import ExtractSignalsStage

    b = _scored(session, "c1", fit=90)
    complaints = [ReviewRecord(iso_date=_recent(5), snippet="nobody answered")
                  for _ in range(4)]
    FetchReviewsStage(FakeReviewProvider(complaints), top_n=1).run(
        session, run_id=None)

    ExtractSignalsStage().run(session, run_id=None)
    before = session.query(Signals).filter_by(business_id=b.id).one()
    assert before.missed_call_complaints_90d == 4

    # The documented recovery: drop the derived signals, re-run the pure
    # stage. `reviews` and `raw_payloads` are what it must rebuild from.
    session.query(Signals).filter_by(business_id=b.id).delete()
    session.commit()
    b.status = BusinessStatus.SITE_SCRAPED
    session.commit()
    ExtractSignalsStage().run(session, run_id=None)

    after = session.query(Signals).filter_by(business_id=b.id).one()
    assert after.missed_call_complaints_90d == 4
    assert after.complaint_quotes == ["nobody answered"] * 4
    assert after.review_velocity_90d is not None


def test_a_never_enriched_business_keeps_review_signals_unknown(session):
    """The other half: an unenriched business must leave the dormant review
    rules skipped, not score them as zero complaints."""
    from app.models.derived import Signals
    from app.pipeline.extract_signals import ExtractSignalsStage

    b = Business(cid="plain", name="plain", status=BusinessStatus.SITE_SCRAPED)
    session.add(b); session.commit()
    ExtractSignalsStage().run(session, run_id=None)

    sig = session.query(Signals).filter_by(business_id=b.id).one()
    assert sig.missed_call_complaints_90d is None
    assert sig.review_velocity_90d is None


class _FailsOnThirdPage:
    """1 and 2 succeed (2 real SerpApi credits consumed), page 3 raises."""

    def __init__(self) -> None:
        self.calls = 0

    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult:
        from app.core.errors import TransientError
        self.calls += 1
        if self.calls >= 3:
            raise TransientError("serpapi: HTTP 500", status_code=500)
        return ReviewResult(
            reviews=[ReviewRecord(iso_date=_recent(5), snippet="a")],
            next_page_token="tok", raw={"page": self.calls})


def test_credits_consumed_before_a_failure_are_still_logged(session):
    """I2(a): FetchReviewsStage had no error handling of any kind and wrote
    the ApiCall row only AFTER collect_recent_reviews returned. A provider
    error on page 3 meant two real credits were consumed and NO row was
    ever written — invisible to `_spent_this_month`, so the 250/month free
    ceiling is computed from an undercount."""
    b = _scored(session, "c1", fit=90)
    provider = _FailsOnThirdPage()

    report = FetchReviewsStage(provider, top_n=1).run(session, run_id=None)

    assert provider.calls == 3
    call = session.query(ApiCall).filter_by(
        business_id=b.id, provider="serpapi").one()
    assert call.credits == 2          # the two pages that really billed
    assert call.status_code == 500
    assert report.failed == 1
    # The failure is this business's, not the stage's: status is untouched
    # so a later run can retry it.
    assert session.query(Business).filter_by(cid="c1").one().status \
        is BusinessStatus.SCORED


def test_a_run_permanent_error_aborts_the_enrich_stage(session):
    class DeadKey:
        def reviews(self, data_id, page_token=None):
            from app.core.errors import RunPermanentError
            raise RunPermanentError("serpapi: HTTP 401", status_code=401)

    for i in range(3):
        _scored(session, f"c{i}", fit=i * 10)
    report = FetchReviewsStage(DeadKey(), top_n=3).run(session, run_id=None)
    assert report.aborted is True
