from app.models.business import Business, BusinessStatus
from app.models.manual import Outcome
from app.services.outcomes import record_outcome


def test_record_outcome_upserts_by_business(session):
    b = Business(cid="c1", name="A", status=BusinessStatus.SCORED)
    session.add(b)
    session.commit()

    record_outcome(session, cid="c1", status="contacted", notes="emailed")
    record_outcome(session, cid="c1", status="replied")

    rows = session.query(Outcome).filter_by(business_id=b.id).all()
    assert len(rows) == 1
    assert rows[0].status == "replied"
    assert rows[0].notes == "emailed"      # earlier notes are preserved
