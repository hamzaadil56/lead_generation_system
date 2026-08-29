"""Model package: importing this package (or any submodule of it) registers
every table on Base.metadata. This matters because SQLAlchemy resolves
string ForeignKey targets (e.g. Business.first_seen_run_id -> "runs.id")
against whatever tables have been registered by the time metadata is used
(create_all, alembic autogenerate), and callers may import only a subset of
the individual model modules directly.
"""

from app.models.base import Base
from app.models.business import Business, BusinessStatus
from app.models.derived import ApiCall, RawPayload, Review, Score, Signals
from app.models.manual import Contact, ManualFacts, Outcome, Ruleset, Suppression
from app.models.run import Run, RunBusiness, SearchQuery

__all__ = [
    "Base",
    "Business",
    "BusinessStatus",
    "Run",
    "RunBusiness",
    "SearchQuery",
    "RawPayload",
    "ApiCall",
    "Review",
    "Signals",
    "Score",
    "ManualFacts",
    "Contact",
    "Outcome",
    "Suppression",
    "Ruleset",
]
