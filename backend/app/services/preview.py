"""Cost and scope preview for the confirm screen (spec section 9).

Reads only. Calling a provider here would defeat the point: the user is
deciding whether to spend, and the preview must not spend.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.run import SearchQuery
from app.schemas.runs import PreviewOut
from app.services.budget import PROVIDER_PRICE_PER_CREDIT
from app.services.search_plan import build_search_plan

# Serper's /maps returns 20 places per page (tests/fixtures/
# serper_maps_houston_hvac.json, confirmed against the real Houston
# response). Used only for the estimate shown to the user.
RESULTS_PER_PAGE = 20

# Serper self-reports 3 credits per page requested, not 1 -- see
# `result.credits == 3` in tests/unit/test_serper_client.py and
# tests/integration/test_discover.py (both citing ADR-021) against the same
# Houston fixture. This estimate uses the confirmed real value rather than
# the smaller number a first draft of this task assumed, since an estimate
# on this screen exists specifically so the number is trustworthy.
CREDITS_PER_PAGE = 3


def preview_search_plan(session: Session, vertical: str, state: str | None,
                        location: str | None, pages: int,
                        verticals_cfg: dict, locations_cfg: dict,
                        recent_days: int = 30) -> PreviewOut:
    plan = build_search_plan(vertical, state, location, verticals_cfg,
                             locations_cfg, pages_per_query=pages)
    queries = plan.queries

    credits = len(queries) * pages * CREDITS_PER_PAGE
    cost = credits * PROVIDER_PRICE_PER_CREDIT.get("serper", 0.0)

    # `search_queries` stores term and location in SEPARATE columns -- there
    # is no combined `query` column -- so the recency check compares the
    # (term, location) pairs and rebuilds the display string the same way
    # SearchPlan.queries does.
    cutoff = datetime.utcnow() - timedelta(days=recent_days)
    executed = {(term, loc) for term, loc in
                session.query(SearchQuery.term, SearchQuery.location)
                .filter(SearchQuery.executed_at >= cutoff).distinct().all()}
    recent = [f"{term} in {loc}"
              for loc in plan.locations for term in plan.search_terms
              if (term, loc) in executed]

    return PreviewOut(
        vertical=vertical,
        queries=queries,
        search_count=len(queries),
        estimated_results=len(queries) * pages * RESULTS_PER_PAGE,
        estimated_cost_usd=round(cost, 4),
        recently_run_queries=sorted(recent),
    )
