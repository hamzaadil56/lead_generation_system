from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ManualFacts(Base):           # PERMANENT — never wiped by a rebuild (ADR-008)
    __tablename__ = "manual_facts"

    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), primary_key=True)
    estimated_employees: Mapped[int | None] = mapped_column(Integer)
    technician_count: Mapped[int | None] = mapped_column(Integer)
    has_office_admin: Mapped[bool | None] = mapped_column(Boolean)
    owner_growth_focused: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(String)
    # default=utcnow: mirrors Business.updated_at / Score.scored_at so
    # constructing ManualFacts without an explicit timestamp still satisfies
    # the NOT NULL column (Task 13's tests rely on this).
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                 onupdate=datetime.utcnow)


class Contact(Base):               # PERMANENT — manual in v1, resolvers in v2
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str | None] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    linkedin_url: Mapped[str | None] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)  # manual | license_registry | website | ...
    confidence: Mapped[float | None] = mapped_column(Float)
    verification_status: Mapped[str | None] = mapped_column(String)  # unverified|valid|risky|invalid|catch_all
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)


class Outcome(Base):               # PERMANENT — the ground truth (ADR-006)
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    status: Mapped[str] = mapped_column(String)  # new|contacted|replied|booked|won|lost
    source: Mapped[str] = mapped_column(String, default="manual")  # manual | email_event
    notes: Mapped[str | None] = mapped_column(String)
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Suppression(Base):           # PERMANENT — required before the first email
    __tablename__ = "suppressions"

    email: Mapped[str] = mapped_column(String, primary_key=True)
    reason: Mapped[str] = mapped_column(String)  # unsubscribed|bounced|complained|manual
    source: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Ruleset(Base):
    __tablename__ = "rulesets"

    version: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    vertical: Mapped[str] = mapped_column(String)
    definition: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime)
