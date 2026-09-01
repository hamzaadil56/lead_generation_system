import pytest

from app.models.business import Business, BusinessStatus
from app.models.manual import ManualFacts, Outcome


@pytest.fixture
def lead(session):
    b = Business(cid="c1", name="Test Air", status=BusinessStatus.SCORED)
    session.add(b)
    session.commit()
    return b


def test_put_outcome_records_the_status(client, session, lead):
    r = client.put("/leads/c1/outcome", json={"status": "contacted"})

    assert r.status_code == 200
    assert session.query(Outcome).filter_by(business_id=lead.id).one().status == "contacted"


def test_put_outcome_updates_rather_than_duplicating(client, session, lead):
    client.put("/leads/c1/outcome", json={"status": "contacted"})
    client.put("/leads/c1/outcome", json={"status": "won"})

    rows = session.query(Outcome).filter_by(business_id=lead.id).all()
    assert len(rows) == 1 and rows[0].status == "won"


def test_put_outcome_rejects_an_unknown_status(client, lead):
    r = client.put("/leads/c1/outcome", json={"status": "vibes"})
    assert r.status_code == 422


def test_put_outcome_404s_for_an_unknown_lead(client):
    r = client.put("/leads/nope/outcome", json={"status": "won"})
    assert r.status_code == 404


def test_put_manual_facts_stores_the_values(client, session, lead):
    r = client.put("/leads/c1/manual-facts",
                   json={"estimated_employees": 25, "runs_google_ads": True})

    assert r.status_code == 200
    facts = session.query(ManualFacts).filter_by(business_id=lead.id).one()
    assert facts.estimated_employees == 25


def test_put_manual_facts_updates_rather_than_duplicating(client, session, lead):
    client.put("/leads/c1/manual-facts", json={"estimated_employees": 10})
    client.put("/leads/c1/manual-facts", json={"estimated_employees": 30})

    rows = session.query(ManualFacts).filter_by(business_id=lead.id).all()
    assert len(rows) == 1 and rows[0].estimated_employees == 30


def test_put_manual_facts_rejects_a_negative_headcount(client, lead):
    r = client.put("/leads/c1/manual-facts", json={"estimated_employees": -5})
    assert r.status_code == 422


def test_get_verticals_lists_the_configured_verticals(client):
    body = client.get("/verticals").json()
    assert "hvac" in [v["name"] for v in body]


def test_get_rulesets_returns_version_and_thresholds(client):
    body = client.get("/rulesets").json()
    assert any(r["version"] == "hvac_v1" for r in body)
