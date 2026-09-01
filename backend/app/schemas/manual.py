from pydantic import BaseModel, Field, field_validator

from app.services.outcomes import VALID


class OutcomeIn(BaseModel):
    # `notes`, not `note`: passed straight through to
    # record_outcome(session, cid, status, notes=...).
    status: str
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def known_status(cls, v: str) -> str:
        if v not in VALID:
            raise ValueError(f"status must be one of {sorted(VALID)}")
        return v


class ManualFactsIn(BaseModel):
    """Fields a human fills in by hand (ADR-008). All optional: the form
    saves whatever the user knows so far.

    Every field here is a real `manual_facts` column -- verified against
    `app/models/manual.py`. Do NOT add a field the table lacks; this plan
    creates no migrations.
    """
    estimated_employees: int | None = Field(default=None, ge=0, le=100000)
    technician_count: int | None = Field(default=None, ge=0, le=10000)
    has_office_admin: bool | None = None
    owner_growth_focused: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)
