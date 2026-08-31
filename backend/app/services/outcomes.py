from datetime import datetime

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.manual import Outcome

VALID = {"new", "contacted", "replied", "booked", "won", "lost"}


def record_outcome(session: Session, cid: str, status: str,
                   notes: str | None = None) -> None:
    if status not in VALID:
        raise ValueError(f"status must be one of {sorted(VALID)}")
    business = session.query(Business).filter_by(cid=cid).one()
    row = session.query(Outcome).filter_by(business_id=business.id).one_or_none()
    if row is None:
        row = Outcome(business_id=business.id, source="manual")
        session.add(row)
    row.status = status
    if notes:
        row.notes = notes
    if status == "contacted" and row.contacted_at is None:
        row.contacted_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    session.commit()
