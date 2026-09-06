"""The contacts CSV: one row per contact, ready for an email tool.

Separate from `app/services/export.py`, which is about leads and stays
untouched. One row per business cannot express a business with three
contacts, and emits a blank-email row for every business with none.
"""
import csv
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.manual import Contact, Suppression
from app.repositories.leads import LeadFilters, filtered_leads

FIELDNAMES = [
    "email", "contact_name", "role", "source", "confidence",
    "business_name", "city", "state", "website", "segment",
    "fit_score", "pain_score", "quadrant",
]


def export_contacts(session: Session, filters: LeadFilters,
                    path: Path) -> int:
    """Write the exportable contacts of the filtered set; return the count.

    Built on `filtered_leads` -- the identical predicate the leads list, the
    leads export and the bulk harvest use -- so "the contacts of the filtered
    set" cannot drift from what the screen shows.

    Three predicates gate what may leave:

    1. `confirmed_at IS NOT NULL` -- a human vouched for this person.
    2. `email IS NOT NULL` -- a contact with no address cannot appear in an
       email export, confirmed or not.
    3. Not present in `suppressions` -- never re-mail someone who asked not
       to be.

    Each is covered by exactly one assertion in
    tests/integration/test_contact_export.py, verified by mutating this
    function and confirming the suite catches it: the cost of a silently
    broken predicate here is emailing someone who unsubscribed.

    `filtered_leads` returns a three-entity query (`Business, Score,
    Outcome.status`); its `.subquery()` therefore carries every column of
    both `Business` and `Score` (Business's `id`/`status` collide with
    Score's and Outcome's and get suffixed `_1` by SQLAlchemy -- inspected
    directly with `.c.keys()` rather than assumed). Only the columns this
    export actually needs are selected out of it by name, so that
    disambiguation is never relied on implicitly.
    """
    base = filtered_leads(session, filters).subquery()

    rows = (session.query(
                Contact,
                base.c.name.label("business_name"),
                base.c.city,
                base.c.state,
                base.c.website,
                base.c.segment,
                base.c.fit_score,
                base.c.pain_score,
                base.c.quadrant)
            .join(base, base.c.id == Contact.business_id)
            .outerjoin(Suppression, func.lower(Suppression.email) == Contact.email)
            .filter(Contact.confirmed_at.isnot(None),
                    Contact.email.isnot(None),
                    Suppression.email.is_(None))
            .order_by((base.c.fit_score * base.c.pain_score).desc(),
                      base.c.id, Contact.id)
            .all())

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for (contact, business_name, city, state, website, segment,
             fit_score, pain_score, quadrant) in rows:
            writer.writerow({
                "email": contact.email,
                "contact_name": contact.name or "",
                "role": contact.role or "",
                "source": contact.source,
                "confidence": (contact.confidence
                              if contact.confidence is not None else ""),
                "business_name": business_name,
                "city": city or "",
                "state": state or "",
                "website": website or "",
                "segment": str(segment) if segment else "",
                "fit_score": fit_score,
                "pain_score": pain_score,
                "quadrant": quadrant,
            })
    return len(rows)
