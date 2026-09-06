"""Read-only contact queries (ADR-024). Writes live in app/services/contacts.py."""
from sqlalchemy.orm import Session

from app.models.manual import Contact
from app.schemas.contacts import ContactOut


def list_for_business(session: Session, business_id: int) -> list[ContactOut]:
    """Primary first, then confirmed, then by confidence.

    Confirmed status outranks confidence deliberately. A manually typed
    contact has `confidence = NULL`, so ordering on confidence alone would
    sort the address a human typed BELOW a harvested 0.3 that is probably a
    stranger.
    """
    rows = (session.query(Contact)
            .filter_by(business_id=business_id)
            .order_by(Contact.is_primary.desc(),
                      Contact.confirmed_at.is_(None).asc(),
                      Contact.confidence.desc().nullslast(),
                      Contact.id.asc())
            .all())
    return [ContactOut.model_validate(row) for row in rows]
