from datetime import datetime

import pytest

from app.models.derived import ApiCall
from app.services.budget import BudgetExceeded, check_budget, spend_usd


def test_spend_sums_cost_across_providers(session):
    session.add(ApiCall(provider="serper", endpoint="maps",
                        credits=3, cost_usd=0.003, status_code=200,
                        created_at=datetime.utcnow()))
    session.add(ApiCall(provider="firecrawl", endpoint="scrape",
                        credits=1, cost_usd=0.002, status_code=200,
                        created_at=datetime.utcnow()))
    session.commit()
    assert spend_usd(session, run_id=None) == pytest.approx(0.005)


def test_check_budget_raises_once_the_ceiling_is_passed(session):
    session.add(ApiCall(provider="serper", endpoint="maps",
                        credits=1, cost_usd=5.0, status_code=200,
                        created_at=datetime.utcnow()))
    session.commit()
    with pytest.raises(BudgetExceeded):
        check_budget(session, run_id=None, ceiling_usd=1.0)


def test_no_ceiling_means_no_check(session):
    check_budget(session, run_id=None, ceiling_usd=None)   # must not raise


def test_spend_derives_dollars_from_credits_when_cost_usd_is_null(session):
    """Correction A: no stage writes `cost_usd` today (they all log
    `credits`, the provider's self-reported unit), so spend_usd must fall
    back to credits x the per-provider price when cost_usd is None."""
    session.add(ApiCall(provider="serper", endpoint="maps",
                        credits=10, cost_usd=None, status_code=200,
                        created_at=datetime.utcnow()))
    session.add(ApiCall(provider="firecrawl", endpoint="scrape",
                        credits=5, cost_usd=None, status_code=200,
                        created_at=datetime.utcnow()))
    session.commit()
    # serper: 10 credits * $0.001 = $0.01; firecrawl: 5 * $0.002 = $0.01
    assert spend_usd(session, run_id=None) == pytest.approx(0.02)
