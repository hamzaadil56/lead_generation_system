import pytest

from app.core.errors import (
    BusinessPermanentError,
    RunPermanentError,
    TransientError,
    classify_http_error,
)


@pytest.mark.parametrize("code,expected", [
    (429, TransientError),
    (500, TransientError),
    (502, TransientError),
    (402, RunPermanentError),        # Firecrawl out of credits — abort the run
    (401, RunPermanentError),        # bad key — do not burn 200 businesses
    (403, RunPermanentError),
    (404, BusinessPermanentError),   # dead site — this is data, not failure
])
def test_http_errors_map_to_the_four_way_taxonomy(code, expected):
    assert classify_http_error(code) is expected


from app.models.business import Business, BusinessStatus
from app.pipeline.base import Stage


class ExplodingStage(Stage):
    name = "test"
    consumes = BusinessStatus.DISCOVERED
    produces = BusinessStatus.SITE_SCRAPED

    def __init__(self, blow_up_on: set[str]) -> None:
        self.blow_up_on = blow_up_on

    def process(self, business, session):
        if business.cid in self.blow_up_on:
            raise ValueError("parser exploded")


def test_one_bad_business_does_not_stop_the_others(session):
    for cid in ["a", "b", "c"]:
        session.add(Business(cid=cid, name=cid, status=BusinessStatus.DISCOVERED))
    session.commit()

    report = ExplodingStage(blow_up_on={"b"}).run(session, run_id=None, limit=10)

    assert report.processed == 2 and report.failed == 1
    b = session.query(Business).filter_by(cid="b").one()
    assert b.status is BusinessStatus.FAILED
    assert b.failed_stage == "test"
    assert "parser exploded" in b.error_message
    # a and c advanced normally
    assert session.query(Business).filter_by(cid="a").one().status \
        is BusinessStatus.SITE_SCRAPED


def test_run_permanent_error_aborts_immediately(session):
    for cid in ["a", "b", "c", "d", "e", "f"]:
        session.add(Business(cid=cid, name=cid, status=BusinessStatus.DISCOVERED))
    session.commit()

    class OutOfCredits(Stage):
        name = "test"
        consumes = BusinessStatus.DISCOVERED
        produces = BusinessStatus.SITE_SCRAPED

        def process(self, business, session):
            raise RunPermanentError("out of credits")

    report = OutOfCredits().run(session, run_id=None, limit=10)
    assert report.aborted is True
    assert report.processed == 0
    # The circuit breaker exists so a dead API key cannot cost 200 failures.
    assert report.failed <= 5


def test_business_permanent_error_advances_business_not_marked_failed(session):
    session.add(Business(cid="dead", name="dead", status=BusinessStatus.DISCOVERED))
    session.commit()

    class DeadSite(Stage):
        name = "test"
        consumes = BusinessStatus.DISCOVERED
        produces = BusinessStatus.SITE_SCRAPED

        def process(self, business, session):
            raise BusinessPermanentError("404 dead domain")

    report = DeadSite().run(session, run_id=None, limit=10)

    assert report.processed == 1
    assert report.failed == 0
    b = session.query(Business).filter_by(cid="dead").one()
    assert b.status is BusinessStatus.SITE_SCRAPED
    assert b.failed_stage is None
    assert b.error_message is None


def test_transient_error_that_never_succeeds_is_handled_as_a_business_failure(session):
    """A TransientError that persists through all retry attempts must reach
    `run`'s exception handling as the original TransientError (via tenacity's
    reraise=True) and be classified as a generic Exception failure — NOT as
    a RunPermanentError (which would trip the circuit breaker) and NOT as an
    unhandled tenacity.RetryError.
    """
    session.add(Business(cid="flaky", name="flaky", status=BusinessStatus.DISCOVERED))
    session.commit()

    call_count = 0

    class AlwaysTransient(Stage):
        name = "test"
        consumes = BusinessStatus.DISCOVERED
        produces = BusinessStatus.SITE_SCRAPED

        def process(self, business, session):
            nonlocal call_count
            call_count += 1
            raise TransientError("upstream timeout")

    report = AlwaysTransient().run(session, run_id=None, limit=10)

    # 3 attempts per tenacity policy (1 initial + 2 retries)
    assert call_count == 3
    assert report.processed == 0
    assert report.failed == 1
    assert report.aborted is False
    b = session.query(Business).filter_by(cid="flaky").one()
    assert b.status is BusinessStatus.FAILED
    assert b.failed_stage == "test"
    assert "upstream timeout" in b.error_message
