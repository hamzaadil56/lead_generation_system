from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReasonOut(BaseModel):
    """One rule's contribution, straight from `Score.reasons`.

    These field names mirror `app.domain.rules.models.RuleReason` EXACTLY,
    because `ScoreStage` persists `asdict(RuleReason)` verbatim
    (`app/pipeline/score.py`) and this model is constructed with
    `ReasonOut(**row)` over that JSON. The pipeline is merged, reviewed
    code and `app/services/export.py` already reads the same keys; the
    schema is the side that has to match.

    It did not: this model declared `id` (a rename of `rule`) and
    `applicable` (invented -- the engine drops non-applicable rules before
    building a reason, `app/domain/rules/engine.py`, so the key has never
    been persisted). Every `GET /leads/{cid}` for a scored business raised
    a pydantic ValidationError. Do not rename a field here without
    changing what the scorer writes; the guard is
    `tests/integration/test_end_to_end.py::
    test_the_lead_detail_api_can_read_the_reasons_the_scorer_writes`,
    which scores real rows and reads them back through the repository.
    """
    rule: str
    track: str
    matched: bool
    points: int
    label: str
    evidence: list[str] | None = None


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
