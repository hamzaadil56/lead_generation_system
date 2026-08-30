import structlog
from sqlalchemy.orm import Session

from app.models.derived import ApiCall

log = structlog.get_logger()

# $/credit per provider, per the project's decision log (ADR budget review).
# SerpApi is free-tier today but still counted so a future paid tier only
# needs this constant changed. An unknown provider prices at $0.00 (see
# _price_for below) so a typo in `provider` under-reports rather than
# crashing the run.
PROVIDER_PRICE_PER_CREDIT: dict[str, float] = {
    "serper": 0.001,
    "firecrawl": 0.002,
    "serpapi": 0.00,
}
DEFAULT_PRICE_PER_CREDIT = 0.00


class BudgetExceeded(Exception):
    # Raised between businesses so a run stops rather than overspending.
    pass


def _price_for(provider: str) -> float:
    if provider not in PROVIDER_PRICE_PER_CREDIT:
        log.warning("budget.unknown_provider_price", provider=provider)
        return DEFAULT_PRICE_PER_CREDIT
    return PROVIDER_PRICE_PER_CREDIT[provider]


def spend_usd(session: Session, run_id: int | None) -> float:
    """Prefers each row's actual logged `cost_usd`. No stage currently
    writes `cost_usd` (they all log `credits`, the provider's self-reported
    unit), so for any row where it is null, dollars are derived from
    `credits` x a per-provider price."""
    q = session.query(ApiCall.provider, ApiCall.credits, ApiCall.cost_usd)
    if run_id is not None:
        q = q.filter(ApiCall.run_id == run_id)

    total = 0.0
    for provider, credits, cost_usd in q.all():
        if cost_usd is not None:
            total += cost_usd
        else:
            total += credits * _price_for(provider)
    return total


def check_budget(session: Session, run_id: int | None,
                 ceiling_usd: float | None) -> None:
    if ceiling_usd is None:
        return
    spent = spend_usd(session, run_id)
    if spent > ceiling_usd:
        raise BudgetExceeded(f"spent ${spent:.2f} of ${ceiling_usd:.2f} ceiling")
