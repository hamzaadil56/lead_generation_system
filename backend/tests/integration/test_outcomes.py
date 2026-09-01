import pytest
from sqlalchemy.exc import IntegrityError

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


def test_a_second_outcome_row_for_the_same_business_is_rejected(session):
    """`get_lead_detail`'s .one_or_none() and list_leads' outerjoin both
    assume at most one Outcome per business. Nothing but a DB constraint can
    guarantee that -- record_outcome's check-then-insert is not atomic."""
    b = Business(cid="c2", name="B", status=BusinessStatus.SCORED)
    session.add(b)
    session.commit()

    session.add(Outcome(business_id=b.id, status="new", source="manual"))
    session.commit()

    session.add(Outcome(business_id=b.id, status="contacted", source="manual"))
    with pytest.raises(IntegrityError):
        session.commit()
