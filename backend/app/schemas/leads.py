from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReasonOut(BaseModel):
    """One rule's contribution, straight from Score.reasons."""
    id: str
    label: str
    track: str
    points: int
    matched: bool
    applicable: bool


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ruleset_version: str
    fit_score: int
    pain_score: int
    quadrant: str
    coverage: float
    scored_at: datetime


class LeadOut(BaseModel):
    """One row in the leads table. Deliberately flat -- the table renders it
    directly."""
    model_config = ConfigDict(from_attributes=True)

    cid: str
    name: str
    city: str | None
    state: str | None
    website: str | None
    phone: str | None          # blank unless phone_is_valid (ADR-013)
    segment: str | None
    review_count: int | None
    fit_score: int
    pain_score: int
    quadrant: str
    coverage: float
    outcome_status: str | None


class EvidenceOut(BaseModel):
    """A verbatim review quote, for outreach copy (spec section 9)."""
    text: str
    rating: int | None
    published_at: datetime | None


class LeadDetailOut(BaseModel):
    lead: LeadOut
    score: ScoreOut | None
    reasons: list[ReasonOut]
    signals: dict[str, object]
    evidence: list[EvidenceOut]
