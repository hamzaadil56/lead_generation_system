import pytest
from sqlalchemy.exc import IntegrityError

from app.models.business import Business, BusinessStatus
from app.models.manual import Contact


def _business(session, cid):
    b = Business(cid=cid, name=f"Business {cid}", status=BusinessStatus.SCORED)
    session.add(b)
    session.flush()
    return b


def test_the_same_email_cannot_be_added_twice_to_one_business(session):
    """Harvest is re-runnable. Without this constraint, running it twice
    doubles every row -- so the constraint is what makes harvest idempotent,
    not any check in the service."""
    business = _business(session, "c-1")
    session.add(Contact(business_id=business.id, email="owner@acme.test",
                        source="manual"))
    session.flush()
    session.add(Contact(business_id=business.id, email="owner@acme.test",
                        source="website"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_the_same_email_may_belong_to_two_different_businesses(session):
    """One person can own two companies. The constraint is per business."""
    a = _business(session, "c-1")
    b = _business(session, "c-2")
    session.add_all([
        Contact(business_id=a.id, email="owner@acme.test", source="manual"),
        Contact(business_id=b.id, email="owner@acme.test", source="manual"),
    ])
    session.flush()          # must not raise


def test_a_business_may_hold_several_contacts_with_no_email(session):
    """Postgres treats NULLs as distinct. A name-and-phone contact with no
    address yet is legitimate contact discovery, and two of them must not
    collide on the unique constraint."""
    business = _business(session, "c-1")
    session.add_all([
        Contact(business_id=business.id, name="John Smith", source="manual"),
        Contact(business_id=business.id, name="Jane Doe", source="manual"),
    ])
    session.flush()          # must not raise


def test_only_one_contact_per_business_can_be_primary(session):
    business = _business(session, "c-1")
    session.add(Contact(business_id=business.id, email="a@acme.test",
                        source="manual", is_primary=True))
    session.flush()
    session.add(Contact(business_id=business.id, email="b@acme.test",
                        source="manual", is_primary=True))
    with pytest.raises(IntegrityError):
        session.flush()


def test_two_businesses_may_each_have_their_own_primary(session):
    a = _business(session, "c-1")
    b = _business(session, "c-2")
    session.add_all([
        Contact(business_id=a.id, email="a@acme.test", source="manual",
                is_primary=True),
        Contact(business_id=b.id, email="b@other.test", source="manual",
                is_primary=True),
    ])
    session.flush()          # partial index is per business, not global


def test_created_at_is_populated_without_being_passed(session):
    business = _business(session, "c-1")
    row = Contact(business_id=business.id, email="a@acme.test", source="manual")
    session.add(row)
    session.flush()
    assert row.created_at is not None


def test_confirmed_at_and_discovery_note_default_to_none(session):
    business = _business(session, "c-1")
    row = Contact(business_id=business.id, email="a@acme.test", source="manual")
    session.add(row)
    session.flush()
    assert row.confirmed_at is None
    assert row.discovery_note is None
