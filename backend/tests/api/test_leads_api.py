import pytest

from app.models.business import Business, BusinessStatus
from app.models.derived import Score


@pytest.fixture
def leads(session):
    for cid, name, fit, pain, quad, state in [
            ("c1", "Go Now Air", 90, 90, "go_now", "TX"),
            ("c2", "Nurture Air", 90, 20, "nurture", "TX"),
            ("c3", "Cold Air", 20, 20, "cold", "CA")]:
        b = Business(cid=cid, name=name, state=state, city="Houston",
                     phone="+17135551234", phone_is_valid=True,
                     website=f"https://{cid}.example.com", review_count=100,
                     vertical="hvac", status=BusinessStatus.SCORED)
        session.add(b)
        session.flush()
        session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                          fit_score=fit, pain_score=pain, quadrant=quad,
                          coverage=0.8, reasons=[]))
    session.commit()


def test_get_leads_returns_every_lead_by_default(client, leads):
    body = client.get("/leads").json()
    assert body["total"] == 3


def test_get_leads_filters_by_quadrant(client, leads):
    body = client.get("/leads?quadrant=go_now").json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Go Now Air"


def test_get_leads_filters_by_state(client, leads):
    assert client.get("/leads?state=CA").json()["total"] == 1


def test_get_leads_orders_by_fit_times_pain(client, leads):
    names = [i["name"] for i in client.get("/leads").json()["items"]]
    assert names[0] == "Go Now Air"


def test_get_leads_rejects_an_oversized_page_size(client, leads):
    """An unbounded page_size is a denial-of-service on our own database."""
    assert client.get("/leads?page_size=100000").status_code == 422


def test_get_leads_returns_an_empty_page_rather_than_404(client):
    body = client.get("/leads").json()
    assert body["total"] == 0 and body["items"] == []


def test_get_lead_detail_returns_reasons_and_signals(client, leads):
    r = client.get("/leads/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["lead"]["name"] == "Go Now Air"
    assert body["score"]["fit_score"] == 90
    assert "reasons" in body and "signals" in body and "evidence" in body


def test_get_lead_detail_404s_for_an_unknown_cid(client, leads):
    assert client.get("/leads/nope").status_code == 404


def test_export_returns_a_csv_attachment(client, leads):
    r = client.get("/leads/export.csv?quadrant=go_now")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("name,phone,website")
    assert len(lines) == 2                      # header + one go_now lead


def test_export_of_an_empty_filter_returns_a_header_only_csv(client, leads):
    r = client.get("/leads/export.csv?quadrant=low_fit")
    assert r.status_code == 200
    assert len(r.text.strip().splitlines()) == 1
