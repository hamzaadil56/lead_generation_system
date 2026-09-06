from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.email import normalize_email


class ContactIn(BaseModel):
    """What a human types. Every field optional except the pair rule below."""
    name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=500)
    is_primary: bool = False

    @field_validator("email")
    @classmethod
    def normalised(cls, v: str | None) -> str | None:
        """Through the same function the harvester uses, so an address the
        harvester saved is always one a human can edit."""
        if v is None or not v.strip():
            return None
        normalised = normalize_email(v)
        if normalised is None:
            raise ValueError("that is not a valid email address")
        return normalised

    @field_validator("linkedin_url")
    @classmethod
    def absolute_url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("linkedin_url must start with http:// or https://")
        return v.strip()

    @model_validator(mode="after")
    def name_or_email(self) -> "ContactIn":
        # `phone` is deliberately NOT run through validate_phone: that gate
        # exists because Serper returns street addresses in `phoneNumber`
        # (ADR-013). A hand-typed direct line or extension is trusted.
        if not (self.name or "").strip() and not self.email:
            raise ValueError("a contact needs at least a name or an email")
        return self


class ContactUpdate(ContactIn):
    """The edit body. Same fields, same per-field validation -- but WITHOUT
    the name-or-email rule.

    That rule belongs to creation. On an edit the body is applied with
    `exclude_unset`, so `{"role": "GM"}` is a legitimate partial update of a
    contact that already has a name; inheriting the rule would reject it as
    422 and make every partial edit impossible.

    The invariant is not dropped, only moved: `update_contact` re-checks the
    RESULTING row, so an edit that blanks both name and email still fails.
    """

    @model_validator(mode="after")
    def name_or_email(self) -> "ContactIn":
        return self


class ContactOut(BaseModel):
    """One contact as the dashboard sees it.

    `verification_status` is deliberately absent. It answers "is this
    deliverable?", nothing in v1 knows, and rendering a permanent
    "unverified" badge beside a "Confirmed" badge invites exactly the
    conflation ADR-029 exists to prevent.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    role: str | None
    email: str | None
    phone: str | None
    linkedin_url: str | None
    source: str                     # "manual" | "website"
    confidence: float | None        # NULL for a human-typed contact
    discovery_note: str | None      # why the harvester scored it that way
    is_primary: bool
    confirmed_at: datetime | None   # NULL = excluded from the export
    created_at: datetime | None


class HarvestOut(BaseModel):
    created: int
    skipped: int
    candidates: int


class BulkHarvestOut(BaseModel):
    created: int
    businesses: int
