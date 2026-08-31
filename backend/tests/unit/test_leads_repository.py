from datetime import datetime

from app.models.business import Business, BusinessStatus
from app.models.derived import Review, Score, Signals
from app.models.manual import Outcome
from app.repositories.leads import LeadFilters, get_lead_detail, list_leads


def _business(session, cid, name, *, state="TX", fit=80, pain=70,
              quadrant="go_now", phone_valid=True, vertical="hvac"):
    b = Business(cid=cid, name=name, state=state, city="Houston",
                 phone="+17135551234", phone_is_valid=phone_valid,
                 website=f"https://{cid}.example.com", review_count=300,
                 vertical=vertical, status=BusinessStatus.SCORED)
    session.add(b)
    session.flush()
    session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                      fit_score=fit, pain_score=pain, quadrant=quadrant,
                      coverage=0.8, reasons=[
                          {"id": "uses_fsm", "label": "Uses field service software",
                           "track": "fit", "points": 30, "matched": True,
                           "applicable": True}]))
    session.commit()
    return b


def test_list_leads_returns_only_the_requested_quadrant(session):
    _business(session, "c1", "Go Now Air", quadrant="go_now")
    _business(session, "c2", "Cold Air", quadrant="cold", fit=10, pain=10)

    rows, total = list_leads(session, LeadFilters(quadrant="go_now"))

    assert total == 1
    assert [r.name for r in rows] == ["Go Now Air"]


def test_list_leads_orders_by_fit_times_pain_descending(session):
    _business(session, "c1", "Low", fit=50, pain=50)     # 2500
    _business(session, "c2", "High", fit=90, pain=90)    # 8100
    _business(session, "c3", "Mid", fit=70, pain=70)     # 4900

    rows, _ = list_leads(session, LeadFilters())

    assert [r.name for r in rows] == ["High", "Mid", "Low"]


def test_list_leads_never_emits_an_unvalidated_phone(session):
    """ADR-013: Serper's phoneNumber is unreliable, so an unvalidated number
    must not reach the UI where someone would dial it."""
    _business(session, "c1", "Bad Phone", phone_valid=False)

    rows, _ = list_leads(session, LeadFilters())

    assert rows[0].phone is None


def test_list_leads_paginates_without_losing_rows(session):
    for i in range(7):
        _business(session, f"c{i}", f"Air {i}", fit=50 + i, pain=50)

    p1, total = list_leads(session, LeadFilters(), page=1, page_size=3)
    p2, _ = list_leads(session, LeadFilters(), page=2, page_size=3)
    p3, _ = list_leads(session, LeadFilters(), page=3, page_size=3)

    assert total == 7
    assert [len(p1), len(p2), len(p3)] == [3, 3, 1]
    names = {r.name for r in p1 + p2 + p3}
    assert len(names) == 7           # no row appears twice or goes missing


def test_list_leads_filters_by_ruleset_version(session):
    """Scores are keyed (business_id, ruleset_version). Without this filter a
    business scored under two versions would appear twice (ADR-005)."""
    b = _business(session, "c1", "Two Versions")
    session.add(Score(business_id=b.id, ruleset_version="hvac_v2",
                      fit_score=10, pain_score=10, quadrant="cold",
                      coverage=0.5, reasons=[]))
    session.commit()

    rows, total = list_leads(session, LeadFilters(ruleset_version="hvac_v1"))

    assert total == 1
    assert rows[0].fit_score == 80


def test_list_leads_applies_min_fit_and_min_pain_together(session):
    _business(session, "c1", "Both High", fit=90, pain=90)
    _business(session, "c2", "Fit Only", fit=90, pain=10)
    _business(session, "c3", "Pain Only", fit=10, pain=90)

    rows, total = list_leads(session, LeadFilters(min_fit=60, min_pain=60))

    assert total == 1 and rows[0].name == "Both High"


def test_get_lead_detail_returns_reasons_signals_and_evidence(session):
    b = _business(session, "c1", "Detailed Air")
    session.add(Signals(business_id=b.id, closes_before_6pm=True,
                        has_chat_widget=False))
    session.add(Review(business_id=b.id, rating=1, text="nobody ever answers",
                       published_at=datetime(2026, 8, 1), source="serpapi"))
    session.commit()

    detail = get_lead_detail(session, "c1")

    assert detail is not None
    assert detail.lead.name == "Detailed Air"
    assert detail.score is not None and detail.score.fit_score == 80
    assert [r.id for r in detail.reasons] == ["uses_fsm"]
    assert detail.signals["closes_before_6pm"] is True
    assert detail.signals["has_chat_widget"] is False
    assert [e.text for e in detail.evidence] == ["nobody ever answers"]


def test_get_lead_detail_returns_none_for_an_unknown_cid(session):
    assert get_lead_detail(session, "no-such-cid") is None


def test_list_leads_and_detail_show_a_single_outcome_exactly_once(session):
    """Regression guard for the outcomes.business_id uniqueness fix: a
    business with exactly one Outcome must still appear once in list_leads
    with the right total, and get_lead_detail must still surface its
    outcome_status -- the constraint must not break the happy path."""
    b = _business(session, "c1", "One Outcome Air")
    session.add(Outcome(business_id=b.id, status="contacted", source="manual"))
    session.commit()

    rows, total = list_leads(session, LeadFilters())
    assert total == 1
    assert len(rows) == 1
    assert rows[0].outcome_status == "contacted"

    detail = get_lead_detail(session, "c1")
    assert detail is not None
    assert detail.lead.outcome_status == "contacted"


def test_get_lead_detail_works_for_a_business_with_no_score_yet(session):
    """A business mid-pipeline has no Score row. The detail screen must still
    render rather than 500."""
    session.add(Business(cid="c9", name="Unscored", status=BusinessStatus.DISCOVERED))
    session.commit()

    detail = get_lead_detail(session, "c9")

    assert detail is not None and detail.score is None and detail.reasons == []
