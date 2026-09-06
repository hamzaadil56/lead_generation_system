"""Every write to `contacts`. Reads live in app/repositories/contacts.py (ADR-024)."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.manual import Contact
from app.schemas.contacts import ContactIn, ContactUpdate


class DuplicateContactError(Exception):
    """That address is already a contact for this business."""


class ContactWouldBeEmptyError(Exception):
    """An edit that would leave the row with neither a name nor an email."""


def _clear_other_primaries(session: Session, business_id: int,
                           keep_id: int | None = None) -> None:
    """The partial unique index is the backstop, not the mechanism -- an
    INSERT that relied on it would raise instead of replacing the primary."""
    query = session.query(Contact).filter(Contact.business_id == business_id,
                                          Contact.is_primary.is_(True))
    if keep_id is not None:
        query = query.filter(Contact.id != keep_id)
    for row in query.all():
        row.is_primary = False
    session.flush()


def _duplicate_exists(session: Session, business_id: int, email: str | None,
                      exclude_id: int | None = None) -> bool:
    if email is None:
        return False        # NULL emails are distinct; several are allowed
    query = session.query(Contact.id).filter(Contact.business_id == business_id,
                                             Contact.email == email)
    if exclude_id is not None:
        query = query.filter(Contact.id != exclude_id)
    return session.query(query.exists()).scalar()


def create_contact(session: Session, business_id: int,
                   body: ContactIn) -> Contact:
    if _duplicate_exists(session, business_id, body.email):
        raise DuplicateContactError(body.email or "")
    if body.is_primary:
        _clear_other_primaries(session, business_id)
    now = datetime.utcnow()
    row = Contact(
        business_id=business_id, name=body.name, role=body.role,
        email=body.email, phone=body.phone, linkedin_url=body.linkedin_url,
        is_primary=body.is_primary,
        source="manual",
        # Typing an address is looking at it, so manual entry is confirmed on
        # save and needs no second click.
        confirmed_at=now, created_at=now,
        # NOT 1.0. `confidence` is the harvester's model score; a human is not
        # producing a value on that scale, and NULL means "does not apply".
        confidence=None, discovery_note=None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_contact(session: Session, row: Contact,
                   body: ContactUpdate) -> Contact:
    """Partial: an omitted field is left alone, never nulled.

    Editing deliberately does NOT confirm. One action, one meaning -- a
    harvested address you corrected still needs its Confirm click.

    The name-or-email invariant is checked against the MERGED row, not the
    request body: `{"role": "GM"}` mentions neither field and must be allowed,
    while `{"name": "", "email": null}` must not.
    """
    fields = body.model_dump(exclude_unset=True)
    merged_name = fields.get("name", row.name)
    merged_email = fields.get("email", row.email)
    if not (merged_name or "").strip() and not merged_email:
        raise ContactWouldBeEmptyError()
    if "email" in fields and _duplicate_exists(session, row.business_id,
                                               fields["email"],
                                               exclude_id=row.id):
        raise DuplicateContactError(fields["email"] or "")
    if fields.get("is_primary"):
        _clear_other_primaries(session, row.business_id, keep_id=row.id)
    for field, value in fields.items():
        setattr(row, field, value)
    session.commit()
    session.refresh(row)
    return row


def confirm_contact(session: Session, row: Contact) -> Contact:
    """Idempotent: repeat calls do not move the timestamp."""
    if row.confirmed_at is None:
        row.confirmed_at = datetime.utcnow()
        session.commit()
        session.refresh(row)
    return row


def delete_contact(session: Session, row: Contact) -> None:
    """Deleting the primary promotes nobody. The business simply has no
    primary until someone sets one."""
    session.delete(row)
    session.commit()
