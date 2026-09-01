import os

os.environ.setdefault("DATABASE_URL",
                      "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test")
os.environ.setdefault("SERPER_KEY", "x")
os.environ.setdefault("FIRECRAWL_KEY", "x")

from app.models.business import Business, BusinessStatus
from app.models.derived import Review, Score, Signals
from app.models.run import Run
from app.services.seed import seed_demo


def test_seed_creates_leads_in_every_quadrant(session):
    seed_demo(session)
    quadrants = {q for (q,) in session.query(Score.quadrant).distinct()}
    assert quadrants == {"go_now", "nurture", "low_fit", "cold"}


def test_seed_is_idempotent(session):
    first = seed_demo(session)
    second = seed_demo(session)
    assert first == second
    assert session.query(Business).count() == first["businesses"]


def test_seed_is_deterministic(session):
    a = seed_demo(session)
    names_a = sorted(b.name for b in session.query(Business).all())
    # Review and Signals also FK to Business (no ON DELETE CASCADE in the
    # schema), so both must go before Business or the delete below violates
    # a foreign key.
    session.query(Review).delete()
    session.query(Signals).delete()
    session.query(Score).delete()
    session.query(Business).delete()
    session.commit()
    b = seed_demo(session)
    names_b = sorted(x.name for x in session.query(Business).all())
    assert a == b and names_a == names_b


def test_seed_includes_an_unvalidated_phone(session):
    """The UI must render a dash, not a number, for these. Without one in the
    seed, no end-to-end test can prove it."""
    seed_demo(session)
    assert session.query(Business).filter_by(phone_is_valid=False).count() >= 1


def test_seed_includes_a_low_coverage_lead(session):
    seed_demo(session)
    assert session.query(Score).filter(Score.coverage < 0.6).count() >= 1


def test_seed_includes_runs_in_every_status(session):
    seed_demo(session)
    statuses = {s for (s,) in session.query(Run.status).distinct()}
    assert {"complete", "failed"} <= statuses


def test_seed_includes_a_failed_run_with_a_reason(session):
    seed_demo(session)
    failed = session.query(Run).filter_by(status="failed").first()
    assert failed is not None and failed.error


def test_seed_covers_several_segments_including_none(session):
    """The leads table renders `segment`. A seed where every row shared one
    would not exercise the column, and one with no None would not exercise
    the below-the-floor case that `segment_for` returns."""
    seed_demo(session)
    segments = {b.segment for b in session.query(Business).all()}
    assert len(segments) >= 3
    assert None in segments


def test_seeded_businesses_are_scored(session):
    seed_demo(session)
    assert session.query(Business).filter_by(
        status=BusinessStatus.SCORED).count() >= 8
