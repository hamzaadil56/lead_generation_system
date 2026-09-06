"""Read-only queries for the API (ADR-024). Never writes."""
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.models.business import Business
from app.models.derived import Review, Score, Signals
from app.models.manual import ManualFacts, Outcome
from app.repositories.contacts import list_for_business
from app.schemas.leads import (EvidenceOut, LeadDetailOut, LeadOut,
                               ManualFactsOut, ReasonOut, ScoreOut)

DEFAULT_RULESET = "hvac_v1"

# Signals columns that are bookkeeping, not signals the UI should render.
_NON_SIGNAL_COLUMNS = {"business_id", "extracted_at", "extractor_version"}


@dataclass(frozen=True)
class LeadFilters:
    quadrant: str | None = None
    vertical: str | None = None
    state: str | None = None
    min_fit: int = 0
    min_pain: int = 0
    outcome_status: str | None = None
    ruleset_version: str = DEFAULT_RULESET


def _row_to_lead(business: Business, score: Score,
                 outcome_status: str | None) -> LeadOut:
    return LeadOut(
        cid=business.cid,
        name=business.name,
        city=business.city,
        state=business.state,
        website=business.website,
        # ADR-013: an unvalidated Serper phone number must never reach a
        # human who might dial it.
        phone=business.phone if business.phone_is_valid else None,
        segment=str(business.segment) if business.segment else None,
        review_count=business.review_count,
        fit_score=score.fit_score,
        pain_score=score.pain_score,
        quadrant=score.quadrant,
        coverage=score.coverage,
        outcome_status=outcome_status,
    )


def filtered_leads(session: Session,
                   filters: LeadFilters) -> "Query[Any]":
    """The one place a lead filter is expressed.

    Public because `app.services.export` builds the CSV from the same
    predicate: the export is specified as "the filtered set" (spec section 9
    screen 3), and it shipped honouring three of the five filters the list
    endpoint takes, so the screen said one lead and the file held ten. Two
    copies of this WHERE clause is exactly how that happened.
    """
    q = (session.query(Business, Score, Outcome.status)
         .join(Score, Score.business_id == Business.id)
         .outerjoin(Outcome, Outcome.business_id == Business.id)
         .filter(Score.ruleset_version == filters.ruleset_version,
                 Score.fit_score >= filters.min_fit,
                 Score.pain_score >= filters.min_pain))
    if filters.quadrant:
        q = q.filter(Score.quadrant == filters.quadrant)
    if filters.vertical:
        q = q.filter(Business.vertical == filters.vertical)
    if filters.state:
        q = q.filter(Business.state == filters.state)
    if filters.outcome_status:
        q = q.filter(Outcome.status == filters.outcome_status)
    return q


def list_leads(session: Session, filters: LeadFilters, page: int = 1,
               page_size: int = 50) -> tuple[list[LeadOut], int]:
    """One page of leads plus the unpaginated total.

    Ordered by fit x pain descending: the spec's primary sort, and the only
    ordering that respects both tracks without blending them into one stored
    number (ADR-004). NOT ordered by review_count -- ADR-022 forbids
    ratingCount acting as anything but a label.
    """
    q = filtered_leads(session, filters)
    total = q.with_entities(func.count()).order_by(None).scalar() or 0
    rows = (q.order_by((Score.fit_score * Score.pain_score).desc(),
                       Business.id)
             .offset((page - 1) * page_size)
             .limit(page_size)
             .all())
    return [_row_to_lead(b, s, o) for b, s, o in rows], total


def get_lead_detail(session: Session, cid: str,
                    ruleset_version: str = DEFAULT_RULESET
                    ) -> LeadDetailOut | None:
    """Everything the lead detail screen shows, or None if the cid is unknown.

    A business with no Score yet (still mid-pipeline) returns a detail with
    `score=None` rather than 404 -- it exists, it just is not scored.
    """
    business = session.query(Business).filter_by(cid=cid).one_or_none()
    if business is None:
        return None

    score = (session.query(Score)
             .filter_by(business_id=business.id,
                        ruleset_version=ruleset_version)
             .one_or_none())
    outcome = (session.query(Outcome)
               .filter_by(business_id=business.id).one_or_none())

    reasons: list[ReasonOut]
    score_out: ScoreOut | None
    if score is not None:
        lead = _row_to_lead(business, score, outcome.status if outcome else None)
        reasons = [ReasonOut(**r) for r in (score.reasons or [])]
        score_out = ScoreOut.model_validate(score)
    else:
        # Sentinel placeholders for a business with no Score row yet (still
        # mid-pipeline). quadrant="cold"/fit_score=0/pain_score=0 are NOT a
        # real verdict -- nobody has scored this business. `score is None`
        # is the actual signal; callers (and any future frontend) must
        # branch on that, never on `quadrant`, or an unscored business will
        # render as a genuine "cold" lead.
        lead = LeadOut(
            cid=business.cid, name=business.name, city=business.city,
            state=business.state, website=business.website,
            phone=business.phone if business.phone_is_valid else None,
            segment=str(business.segment) if business.segment else None,
            review_count=business.review_count,
            fit_score=0, pain_score=0, quadrant="cold", coverage=0.0,
            outcome_status=outcome.status if outcome else None)
        reasons = []
        score_out = None

    sig = session.query(Signals).filter_by(business_id=business.id).one_or_none()
    signals: dict[str, object] = {}
    if sig is not None:
        signals = {c.name: getattr(sig, c.name)
                   for c in sig.__table__.columns
                   if c.name not in _NON_SIGNAL_COLUMNS}

    evidence = [
        EvidenceOut(text=r.text or "", rating=r.rating,
                    published_at=r.published_at)
        for r in (session.query(Review)
                  .filter_by(business_id=business.id)
                  .order_by(Review.published_at.desc().nullslast())
                  .limit(10).all())
        if r.text
    ]

    # Read back what a human typed. The `manual_facts` overlay in
    # ExtractSignalsStage only reaches `signals` on the next pipeline run, so
    # the Signals row is not a read path for a value saved a second ago.
    facts = (session.query(ManualFacts)
             .filter_by(business_id=business.id).one_or_none())

    return LeadDetailOut(
        lead=lead, score=score_out, reasons=reasons, signals=signals,
        evidence=evidence,
        manual_facts=ManualFactsOut.model_validate(facts) if facts else None,
        contacts=list_for_business(session, business.id))
