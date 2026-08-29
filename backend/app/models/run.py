from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String)  # queued|running|complete|failed
    source: Mapped[str] = mapped_column(String)  # ui|cli
    search_plan: Mapped[dict] = mapped_column(JSON)  # a Run is always created from a SearchPlan
    # nullable: end-of-run counts ({searched, found, new}); absent while the
    # run is still `queued`/`running` and only written on completion.
    stats: Mapped[dict | None] = mapped_column(JSON)
    max_cost_usd: Mapped[float | None] = mapped_column(Float)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    actual_cost: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(String)


class RunBusiness(Base):
    __tablename__ = "run_businesses"

    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    is_new: Mapped[bool] = mapped_column(Boolean)

    __table_args__ = (PrimaryKeyConstraint("run_id", "business_id"),)


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    term: Mapped[str] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String)
    executed_at: Mapped[datetime] = mapped_column(DateTime)
    result_count: Mapped[int] = mapped_column(Integer)
