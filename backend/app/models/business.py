import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Segment is defined ONCE, in app/domain/segments.py (Task 3), and imported
# here. The domain may not import models, so the dependency runs this way
# only. Do not re-declare it in this module.
from app.domain.segments import Segment


class BusinessStatus(enum.StrEnum):
    DISCOVERED = "discovered"
    PLACE_FETCHED = "place_fetched"
    SITE_SCRAPED = "site_scraped"
    SIGNALS_EXTRACTED = "signals_extracted"
    SCORED = "scored"
    FILTERED_OUT = "filtered_out"
    FAILED = "failed"


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    cid: Mapped[str] = mapped_column(String, unique=True, index=True)
    place_id: Mapped[str | None] = mapped_column(String)
    fid: Mapped[str | None] = mapped_column(String)

    name: Mapped[str] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(String)   # absent for service-area businesses
    city: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)

    phone: Mapped[str | None] = mapped_column(String)
    phone_is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    website: Mapped[str | None] = mapped_column(String)

    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    segment: Mapped[Segment | None] = mapped_column(Enum(Segment))

    primary_category: Mapped[str | None] = mapped_column(String)
    types: Mapped[list | None] = mapped_column(JSON)
    opening_hours: Mapped[dict | None] = mapped_column(JSON)
    booking_links: Mapped[list | None] = mapped_column(JSON)

    vertical: Mapped[str | None] = mapped_column(String)
    status: Mapped[BusinessStatus] = mapped_column(Enum(BusinessStatus), index=True)
    failed_stage: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(String)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    first_seen_run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                 onupdate=datetime.utcnow)
