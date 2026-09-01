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
    # a foreign key. Run is cleared too: `_already_seeded` only checks
    # Business, so leaving the two seed Run rows in place while wiping
    # Business would make the reseed below insert a *second* pair of Run
    # rows alongside the surviving ones -- a real wipe clears all of it.
    session.query(Review).delete()
    session.query(Signals).delete()
    session.query(Score).delete()
    session.query(Business).delete()
    session.query(Run).delete()
    session.commit()
    b = seed_demo(session)
    names_b = sorted(x.name for x in session.query(Business).all())
    assert a == b and names_a == names_b


def test_seed_is_deterministic_in_every_column(session):
    """The count-level check above would not catch a column left to an
    ORM-side default (e.g. `datetime.utcnow`) that varies between the two
    inserts. This snapshots every non-surrogate column of every seeded row
    and diffs the two inserts directly."""
    def snapshot():
        cid_of = {b.id: b.cid for b in session.query(Business).all()}

        def row(obj, table, drop):
            d = {c.name: getattr(obj, c.name) for c in table.columns}
            for key in drop:
                d.pop(key, None)
            return d

        businesses = {
            b.cid: row(b, Business.__table__, {"id", "first_seen_run_id"})
            for b in session.query(Business).all()
        }
        signals = {
            cid_of[s.business_id]: row(s, Signals.__table__, {"business_id"})
            for s in session.query(Signals).all()
        }
        scores = {
            cid_of[s.business_id]: row(s, Score.__table__, {"id", "business_id"})
            for s in session.query(Score).all()
        }
        reviews = {
            cid_of[r.business_id]: row(r, Review.__table__, {"id", "business_id"})
            for r in session.query(Review).all()
        }
        runs = sorted(
            (row(r, Run.__table__, {"id"}) for r in session.query(Run).all()),
            key=lambda d: str(d["status"]))
        return businesses, signals, scores, reviews, runs

    seed_demo(session)
    first = snapshot()

    session.query(Review).delete()
    session.query(Signals).delete()
    session.query(Score).delete()
    session.query(Business).delete()
    session.query(Run).delete()
    session.commit()

    seed_demo(session)
    second = snapshot()

    assert first == second


def test_seed_reports_actual_counts_when_partially_deleted(session):
    """The idempotence guard is a coarse `cid LIKE 'seed-%'` check -- it does
    not verify the seed is intact. Deleting one seeded row and reseeding
    must not repair it, but the returned counts must reflect reality, not
    the constant full-dataset size."""
    first = seed_demo(session)

    victim = (session.query(Score)
              .join(Business, Score.business_id == Business.id)
              .filter(Business.cid == "seed-01")
              .one())
    session.delete(victim)
    session.commit()

    second = seed_demo(session)

    assert second["businesses"] == first["businesses"]
    assert second["scores"] == first["scores"] - 1
    assert session.query(Score).count() == first["scores"] - 1


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
