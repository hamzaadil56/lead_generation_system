import pytest

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


class _RateLimitedProvider:
    """Raises what SerperClient now raises for an HTTP 429."""

    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, page: int = 1):
        from app.core.errors import TransientError
        self.calls += 1
        raise TransientError("serper: HTTP 429", status_code=429)


class _DeadKeyProvider:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, page: int = 1):
        from app.core.errors import RunPermanentError
        self.calls += 1
        raise RunPermanentError("serper: HTTP 401", status_code=401)


def test_a_serper_429_is_retried_three_times_not_once(session):
    """C2: the spec mandates 3 attempts with backoff. Before the clients
    spoke the taxonomy, a 429 arrived as a raw httpx.HTTPStatusError,
    tenacity did not match it, DiscoverStage had no try/except, and the
    run died after exactly ONE provider call."""
    from app.core.errors import TransientError
    provider = _RateLimitedProvider()
    with pytest.raises(TransientError):
        DiscoverStage(provider).discover(session, run_id=None, plan=PLAN)
    assert provider.calls == 3


def test_a_dead_serper_key_aborts_discovery_instead_of_reporting_success(session):
    provider = _DeadKeyProvider()
    report = DiscoverStage(provider).discover(session, run_id=None, plan=PLAN)
    assert report.aborted is True
    assert report.reason is not None
    assert provider.calls == 1          # not retried — it will never succeed


def test_the_trailing_pages_api_call_is_not_discarded(session):
    """I2(b): the `break` on an empty page fired after the ApiCall and
    SearchQuery rows were added but BEFORE session.commit(). For every
    query but the last, the next query's commit rescued them; the final
    query's were dropped when the session closed uncommitted. Reproduced
    as 2 real Serper calls, 1 ApiCall row persisted."""
    from app.models.derived import ApiCall
    from app.models.run import SearchQuery

    plan = SearchPlan(vertical="hvac", search_terms=["hvac contractor"],
                      locations=["Houston, TX"], pages_per_query=2)
    provider = FakeSearchProvider()
    DiscoverStage(provider).discover(session, run_id=None, plan=plan)
    assert len(provider.calls) == 2

    # What `get_session()` does when the stage returns without committing.
    session.rollback()

    assert session.query(ApiCall).filter_by(provider="serper").count() == 2
    assert session.query(SearchQuery).count() == 2


def test_a_failed_serper_call_is_still_logged_to_api_calls(session):
    """The global constraint is 'every API call logs actual cost'. A call
    that 401s consumed no credits but must still leave an honest row —
    `api_calls` is the table you would use to diagnose the incident."""
    from app.models.derived import ApiCall
    DiscoverStage(_DeadKeyProvider()).discover(session, run_id=None, plan=PLAN)
    session.rollback()

    call = session.query(ApiCall).filter_by(provider="serper").one()
    assert call.status_code == 401
    assert call.credits == 0
