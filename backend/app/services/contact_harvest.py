"""Contact discovery from HTML already in the database.

Reads `raw_payloads.raw_text`, which Firecrawl filled and ADR-003 keeps
forever. Calls no provider and costs nothing, so re-running is free.

INSERT-ONLY. It never updates and never deletes. `contacts` is a PERMANENT
table (ADR-008) holding rows a human typed, and a harvest that could
overwrite them would make the manual form untrustworthy.

Deliberately NOT a pipeline stage. A new `Business.status` would force every
existing business through a new state and couple discovery to a run's
lifecycle and its circuit breaker, and harvesting has to work retrospectively
on businesses scraped last week -- which are already past any status a new
stage could select on.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.extractors.emails import HarvestedEmail, extract_emails
from app.models.business import Business
from app.models.derived import RawPayload
from app.models.manual import Contact
from app.repositories.leads import LeadFilters, filtered_leads

#: Only Firecrawl payloads hold page HTML; Serper and SerpApi hold JSON.
FIRECRAWL = "firecrawl"
#: `Contact.source` for anything this module writes (spec section 8).
SOURCE = "website"


@dataclass(frozen=True)
class HarvestResult:
    created: int
    skipped: int
    candidates: int


@dataclass(frozen=True)
class BulkHarvestResult:
    created: int
    businesses: int


def harvest_for_business(session: Session, business_id: int) -> HarvestResult:
    """Insert every new usable address found in this business's cached pages."""
    business = session.get(Business, business_id)
    if business is None:
        return HarvestResult(created=0, skipped=0, candidates=0)

    payloads = (session.query(RawPayload)
                .filter_by(business_id=business_id, source=FIRECRAWL)
                .order_by(RawPayload.fetched_at.asc(), RawPayload.id.asc())
                .all())

    # Deduplicated across EVERY page before a single insert. The same footer
    # address appears on all four allowlisted pages on most sites, and two
    # inserts of it in one transaction would raise IntegrityError against
    # uq_contacts_business_email and abort the whole harvest.
    best: dict[str, HarvestedEmail] = {}
    for payload in payloads:
        for candidate in extract_emails(payload.raw_text or "",
                                        site_domain=business.website,
                                        business_name=business.name):
            current = best.get(candidate.email)
            if current is None or candidate.confidence > current.confidence:
                best[candidate.email] = candidate

    # Skipping addresses that already exist rather than letting the constraint
    # raise: an IntegrityError here would roll back the whole harvest, so the
    # second run of a ten-address site would save none of the eleventh.
    existing = {
        email for (email,) in session.query(Contact.email)
        .filter(Contact.business_id == business_id,
                Contact.email.isnot(None)).all()
    }

    now = datetime.utcnow()
    created = 0
    for candidate in sorted(best.values(),
                            key=lambda c: (-c.confidence, c.email)):
        if candidate.email in existing:
            continue
        session.add(Contact(
            business_id=business_id,
            email=candidate.email,
            source=SOURCE,
            confidence=candidate.confidence,
            discovery_note=candidate.note,
            # Never guessed by a machine: `role` is a human's judgement, and
            # `confirmed_at` is the whole point of the export gate.
            role=None,
            confirmed_at=None,
            is_primary=False,
            created_at=now,
        ))
        created += 1

    session.commit()
    return HarvestResult(created=created,
                         skipped=len(best) - created,
                         candidates=len(best))


def harvest_for_filters(session: Session,
                        filters: LeadFilters) -> BulkHarvestResult:
    """Harvest every business in the filtered set.

    Built on `filtered_leads` -- the identical predicate the leads list, the
    leads export and the contacts export use. A bulk harvest that ignored its
    filters would walk every business in the database.
    """
    business_ids = [business.id
                    for business, _score, _status
                    in filtered_leads(session, filters).all()]
    created = sum(harvest_for_business(session, bid).created
                  for bid in business_ids)
    return BulkHarvestResult(created=created, businesses=len(business_ids))
