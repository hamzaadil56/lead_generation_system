from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawPayload(Base):            # PERMANENT, append-only (ADR-003)
    __tablename__ = "raw_payloads"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    source: Mapped[str] = mapped_column(String)  # serper_maps | firecrawl | serpapi_reviews
    url: Mapped[str | None] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    payload: Mapped[dict] = mapped_column(JSON)
    raw_text: Mapped[str | None] = mapped_column(String)


class ApiCall(Base):               # PERMANENT — cost accounting + budget guard
    __tablename__ = "api_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id"))
    provider: Mapped[str] = mapped_column(String)  # serper | firecrawl | serpapi
    endpoint: Mapped[str] = mapped_column(String)
    credits: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # monthly ceiling queries it


class Review(Base):                # REBUILDABLE
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    author: Mapped[str | None] = mapped_column(String)
    rating: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at_is_approximate: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String)


class Signals(Base):               # REBUILDABLE — all columns nullable
    __tablename__ = "signals"

    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), primary_key=True)
    # from Serper /maps (free)
    has_booking_link: Mapped[bool | None] = mapped_column(Boolean)
    booking_vendor: Mapped[str | None] = mapped_column(String)
    is_phone_only: Mapped[bool | None] = mapped_column(Boolean)
    is_24_7: Mapped[bool | None] = mapped_column(Boolean)
    closes_before_6pm: Mapped[bool | None] = mapped_column(Boolean)
    closed_weekends: Mapped[bool | None] = mapped_column(Boolean)
    hours_parse_failed: Mapped[bool | None] = mapped_column(Boolean)
    segment: Mapped[str | None] = mapped_column(String)
    # from Firecrawl (scraped subset only)
    has_chat_widget: Mapped[bool | None] = mapped_column(Boolean)
    chat_vendor: Mapped[str | None] = mapped_column(String)
    has_contact_form: Mapped[bool | None] = mapped_column(Boolean)
    software_from_html: Mapped[str | None] = mapped_column(String)  # secondary vendor source, ADR-023
    runs_google_ads: Mapped[bool | None] = mapped_column(Boolean)
    has_meta_pixel: Mapped[bool | None] = mapped_column(Boolean)
    claims_24_7: Mapped[bool | None] = mapped_column(Boolean)
    website_status: Mapped[str | None] = mapped_column(String)  # ok | none | dead | parked
    team_page_headcount: Mapped[int | None] = mapped_column(Integer)
    # from SerpApi enrichment (top N only; absent = dormant rules skip)
    review_velocity_90d: Mapped[float | None] = mapped_column(Float)
    missed_call_complaints_90d: Mapped[int | None] = mapped_column(Integer)
    complaint_quotes: Mapped[dict | list | None] = mapped_column(JSON)
    # from manual_facts overlay
    estimated_employees: Mapped[int | None] = mapped_column(Integer)
    employee_est_source: Mapped[str | None] = mapped_column(String)
    has_office_admin: Mapped[bool | None] = mapped_column(Boolean)
    owner_growth_focused: Mapped[bool | None] = mapped_column(Boolean)
    extracted_at: Mapped[datetime] = mapped_column(DateTime)
    extractor_version: Mapped[str] = mapped_column(String)


class Score(Base):                 # REBUILDABLE
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    ruleset_version: Mapped[str] = mapped_column(String)
    fit_score: Mapped[int] = mapped_column(Integer)
    pain_score: Mapped[int] = mapped_column(Integer)
    quadrant: Mapped[str] = mapped_column(String)
    coverage: Mapped[float] = mapped_column(Float)
    reasons: Mapped[dict | list] = mapped_column(JSON)
    # default=utcnow: Step 1's test constructs Score without scored_at while
    # keeping the column NOT NULL, matching the Business.created_at pattern.
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("business_id", "ruleset_version"),)
