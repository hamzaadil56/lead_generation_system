from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunCreate(BaseModel):
    """What the UI posts to start a run.

    Mirrors `build_search_plan`'s arguments, which raises ValueError when
    neither state nor location is given -- caught here instead so the
    client gets a 422 naming the field rather than a 400 from deeper in.
    """
    vertical: str
    state: str | None = None
    location: str | None = None
    pages: int = Field(default=5, ge=1, le=20)
    max_cost_usd: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def one_of_state_or_location(self) -> Self:
        if not self.state and not self.location:
            raise ValueError("one of state or location is required")
        return self


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    source: str
    search_plan: dict[str, Any]
    stats: dict[str, Any] | None
    max_cost_usd: float | None
    estimated_cost: float | None
    actual_cost: float | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class PreviewOut(BaseModel):
    """The confirm screen (spec section 9, screen 1). Nothing is spent until
    the user posts the run itself."""
    vertical: str
    queries: list[str]
    search_count: int
    estimated_results: int
    estimated_cost_usd: float
    recently_run_queries: list[str]
