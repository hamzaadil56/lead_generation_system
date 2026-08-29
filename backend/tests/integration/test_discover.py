from app.clients.fakes import FakeSearchProvider
from app.pipeline.discover import DiscoverStage
from app.services.search_plan import SearchPlan
from app.models.business import Business, BusinessStatus, Segment

PLAN = SearchPlan(vertical="hvac", search_terms=["hvac contractor"],
                  locations=["Houston, TX"], pages_per_query=1)


def test_inserts_businesses_with_segment_and_validated_phone(session):
    stage = DiscoverStage(FakeSearchProvider())
    stage.discover(session, run_id=None, plan=PLAN)

    air_tech = session.query(Business).filter_by(
        cid="16433610908791049931").one()
    assert air_tech.segment is Segment.ENTERPRISE     # 6,445 reviews
    assert air_tech.phone == "+18326805546"
    assert air_tech.phone_is_valid is True
    assert air_tech.status is BusinessStatus.DISCOVERED


def test_prefilter_is_only_has_a_website(session):
    """ADR-022: ratingCount is a label, never a gate."""
    DiscoverStage(FakeSearchProvider()).discover(session, run_id=None, plan=PLAN)

    # Heights A/C has 72 reviews and a website — it must survive.
    heights = session.query(Business).filter_by(cid="6096296143558169934").one()
    assert heights.status is BusinessStatus.DISCOVERED
    assert heights.segment is Segment.EMERGING

    filtered = session.query(Business).filter_by(
        status=BusinessStatus.FILTERED_OUT).all()
    assert all(b.website is None for b in filtered)


def test_rediscovery_does_not_reinsert_or_reset_status(session):
    """The dedupe mechanism from ADR-013."""
    stage = DiscoverStage(FakeSearchProvider())
    stage.discover(session, run_id=None, plan=PLAN)
    first_count = session.query(Business).count()

    b = session.query(Business).filter_by(cid="16433610908791049931").one()
    b.status = BusinessStatus.SCORED
    session.commit()

    stage.discover(session, run_id=None, plan=PLAN)
    assert session.query(Business).count() == first_count
    assert session.query(Business).filter_by(
        cid="16433610908791049931").one().status is BusinessStatus.SCORED


def test_raw_payload_and_actual_credits_are_recorded(session):
    from app.models.derived import RawPayload, ApiCall
    DiscoverStage(FakeSearchProvider()).discover(session, run_id=None, plan=PLAN)

    assert session.query(RawPayload).count() >= 20      # ADR-003
    call = session.query(ApiCall).filter_by(provider="serper").first()
    assert call.credits == 3                            # self-reported (ADR-021)
