from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    text,
)
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
    # Answers "is this address deliverable?" (ADR-029). Nothing in v1 ever
    # writes this column -- deliverability checking does not exist yet -- so
    # it stays NULL for every row, manual or harvested. Do NOT conflate it
    # with `confirmed_at` below: that column answers "did a human decide
    # this is a person worth emailing, and when?", a judgement a human makes
    # regardless of whether the address bounces.
    verification_status: Mapped[str | None] = mapped_column(String)  # unverified|valid|risky|invalid|catch_all
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    # default=utcnow: the column existed from the initial migration but
    # nothing ever set it, so every row would have carried a NULL creation
    # time. server_default mirrors the `now()` the c9af97b1b25c migration set
    # at the database level -- without it here, `alembic upgrade head` and
    # `Base.metadata.create_all` (what tests/conftest.py builds) produce
    # different schemas, and `alembic revision --autogenerate` sees a
    # permanent phantom diff.
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=text("now()"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Answers "did a human decide this is a person worth emailing, and when?"
    # NULL means nobody has vouched for it, and the contacts export skips it.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Why the harvester scored this address the way it did, in words. NULL for
    # manually typed contacts.
    discovery_note: Mapped[str | None] = mapped_column(String)

    # BOTH of these are declared here and not only in the Alembic revision.
    # tests/conftest.py builds the test schema with Base.metadata.create_all,
    # so a constraint that lives only in a migration is invisible to the
    # entire suite -- the duplicate-email test above would pass against a
    # schema that has no unique constraint at all.
    __table_args__ = (
        # Makes harvest idempotent: re-running inserts nothing the second
        # time. NULL emails stay distinct under Postgres, so several
        # name-only contacts per business remain legal.
        UniqueConstraint("business_id", "email",
                         name="uq_contacts_business_email"),
        # At most one primary per business, enforced by the database rather
        # than by every write path remembering to clear the others.
        Index("uq_contacts_one_primary", "business_id", unique=True,
              postgresql_where=text("is_primary")),
    )


class Outcome(Base):               # PERMANENT — the ground truth (ADR-006)
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    status: Mapped[str] = mapped_column(String)  # new|contacted|replied|booked|won|lost
    source: Mapped[str] = mapped_column(String, default="manual")  # manual | email_event
    notes: Mapped[str | None] = mapped_column(String)
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    # At most one Outcome per business (repository fix round 1): list_leads'
    # outerjoin and get_lead_detail's .one_or_none() both assume this, and
    # record_outcome's check-then-insert is not atomic, so only a DB
    # constraint can actually guarantee it. Named explicitly so the Alembic
    # downgrade is portable.
    __table_args__ = (UniqueConstraint("business_id", name="uq_outcomes_business_id"),)


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
