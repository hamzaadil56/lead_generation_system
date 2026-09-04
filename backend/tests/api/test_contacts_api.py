import inspect
from datetime import datetime

import pytest

from app.models.business import Business, BusinessStatus
from app.models.derived import RawPayload, Score
from app.models.manual import Contact

# Every test below talks about lead "c-1" (and sometimes "c-2") without
# asking for it explicitly, mirroring test_leads_api.py's `leads` fixture but
# scoped to what contact writes need: businesses that exist, nothing scored.
@pytest.fixture(autouse=True)
def businesses(session):
    for cid in ("c-1", "c-2"):
        session.add(Business(cid=cid, name=f"Business {cid}",
                             status=BusinessStatus.DISCOVERED))
    session.commit()


@pytest.fixture
def harvested_contact(session):
    """A Contact as the harvester would have left it: unconfirmed, scored,
    no name -- the shape editing and confirming both need to act on."""
    business = session.query(Business).filter_by(cid="c-1").one()
    row = Contact(business_id=business.id, name=None, role=None,
                 email="found@leisuration.test", source="website",
                 confidence=0.9, confirmed_at=None, is_primary=False,
                 created_at=datetime.utcnow())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@pytest.fixture
def business_with_html(session):
    """Lead c-1 with a cached Firecrawl page holding one harvestable
    address, matching its own website domain so it scores high enough to be
    created."""
    business = session.query(Business).filter_by(cid="c-1").one()
    business.website = "https://leisuration.test"
    session.add(RawPayload(business_id=business.id, source="firecrawl",
                           url="https://leisuration.test/contact",
                           fetched_at=datetime(2026, 9, 1), payload={},
                           raw_text="<p>owner@leisuration.test</p>"))
    session.commit()
    return business


def test_creating_a_contact_marks_it_confirmed_and_manual(client, session):
    """Typing an address is looking at it, so manual entry needs no second
    confirm click."""
    r = client.post("/leads/c-1/contacts",
                    json={"name": "John Smith", "role": "Owner",
                          "email": "John@Acme.test"})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "john@acme.test"      # normalised
    assert body["source"] == "manual"
    assert body["confirmed_at"] is not None
    # NOT 1.0: confidence is the harvester's model score and a human is not
    # producing a value on that scale.
    assert body["confidence"] is None


def test_a_duplicate_address_is_a_409_not_a_500(client, session):
    """The unique constraint is load-bearing for harvest idempotency, which
    means an ordinary user action -- typing an address that was already
    harvested -- hits it on a normal path. An unhandled IntegrityError there
    is a 500 that also poisons the session."""
    payload = {"name": "John", "email": "john@acme.test"}
    assert client.post("/leads/c-1/contacts", json=payload).status_code == 201
    r = client.post("/leads/c-1/contacts", json=payload)
    assert r.status_code == 409
    assert "already a contact" in r.json()["detail"]


def test_the_same_address_on_a_different_lead_is_fine(client, session):
    payload = {"name": "John", "email": "john@acme.test"}
    assert client.post("/leads/c-1/contacts", json=payload).status_code == 201
    assert client.post("/leads/c-2/contacts", json=payload).status_code == 201


def test_creating_against_an_unknown_lead_is_404(client):
    r = client.post("/leads/nope/contacts", json={"name": "John"})
    assert r.status_code == 404


def test_a_contact_with_neither_name_nor_email_is_422(client, session):
    r = client.post("/leads/c-1/contacts", json={"phone": "+17135550100"})
    assert r.status_code == 422


def test_editing_leaves_omitted_fields_alone(client, session):
    """Partial save must not null the columns it did not mention -- the bug
    the manual-facts form shipped with."""
    created = client.post("/leads/c-1/contacts",
                          json={"name": "John", "role": "Owner",
                                "email": "john@acme.test"}).json()
    r = client.put(f"/contacts/{created['id']}", json={"role": "GM"})
    assert r.status_code == 200
    assert r.json()["role"] == "GM"
    assert r.json()["name"] == "John"
    assert r.json()["email"] == "john@acme.test"


def test_a_partial_edit_that_mentions_neither_name_nor_email_is_allowed(
        client, session):
    """The name-or-email rule belongs to creation. If ContactIn's validator
    were inherited by the edit body, EVERY partial edit would be a 422."""
    created = client.post("/leads/c-1/contacts",
                          json={"name": "John", "email": "j@acme.test"}).json()
    r = client.put(f"/contacts/{created['id']}", json={"role": "GM"})
    assert r.status_code == 200


def test_an_edit_that_would_blank_both_name_and_email_is_422(client, session):
    """The invariant moved to the merged row; it did not disappear."""
    created = client.post("/leads/c-1/contacts",
                          json={"name": "John", "email": "j@acme.test"}).json()
    r = client.put(f"/contacts/{created['id']}",
                   json={"name": "", "email": None})
    assert r.status_code == 422


def test_editing_does_not_confirm(client, session, harvested_contact):
    """One action, one meaning. Correcting a harvested address still needs
    its Confirm click."""
    r = client.put(f"/contacts/{harvested_contact.id}",
                   json={"name": "John Smith"})
    assert r.status_code == 200
    assert r.json()["confirmed_at"] is None


def test_confirm_sets_the_timestamp(client, session, harvested_contact):
    r = client.post(f"/contacts/{harvested_contact.id}/confirm")
    assert r.status_code == 200
    assert r.json()["confirmed_at"] is not None


def test_confirm_is_idempotent(client, session, harvested_contact):
    first = client.post(f"/contacts/{harvested_contact.id}/confirm").json()
    second = client.post(f"/contacts/{harvested_contact.id}/confirm").json()
    assert first["confirmed_at"] == second["confirmed_at"]


def test_setting_primary_clears_the_previous_primary(client, session):
    a = client.post("/leads/c-1/contacts",
                    json={"name": "A", "email": "a@acme.test",
                          "is_primary": True}).json()
    b = client.post("/leads/c-1/contacts",
                    json={"name": "B", "email": "b@acme.test",
                          "is_primary": True}).json()
    detail = client.get("/leads/c-1").json()
    primaries = [c["id"] for c in detail["contacts"] if c["is_primary"]]
    assert primaries == [b["id"]]
    assert a["id"] not in primaries


def test_deleting_a_contact(client, session):
    created = client.post("/leads/c-1/contacts",
                          json={"name": "John", "email": "j@acme.test"}).json()
    assert client.delete(f"/contacts/{created['id']}").status_code == 204
    assert client.get("/leads/c-1").json()["contacts"] == []


def test_unknown_contact_ids_are_404(client):
    assert client.put("/contacts/999999", json={"name": "x"}).status_code == 404
    assert client.delete("/contacts/999999").status_code == 404
    assert client.post("/contacts/999999/confirm").status_code == 404


def test_contacts_appear_on_the_lead_detail(client, session):
    client.post("/leads/c-1/contacts",
                json={"name": "John", "email": "john@acme.test"})
    detail = client.get("/leads/c-1").json()
    assert [c["email"] for c in detail["contacts"]] == ["john@acme.test"]


def test_verification_status_is_never_exposed(client, session):
    created = client.post("/leads/c-1/contacts",
                          json={"name": "John", "email": "j@acme.test"}).json()
    assert "verification_status" not in created


def test_harvesting_one_lead(client, session, business_with_html):
    r = client.post("/leads/c-1/contacts/harvest")
    assert r.status_code == 200
    assert r.json()["created"] >= 1


def test_harvesting_a_lead_with_no_html_is_a_zero_not_an_error(client, session):
    r = client.post("/leads/c-1/contacts/harvest")
    assert r.status_code == 200
    assert r.json() == {"created": 0, "skipped": 0, "candidates": 0}


def test_bulk_harvest_honours_its_filters(client, session):
    """FastAPI silently ignores query params an endpoint does not declare, so
    a filter missing here does not fail -- the harvest just walks the whole
    table. Same failure mode as the leads export (commit f7b1ef2), worse
    blast radius.

    Built explicitly here rather than through a shared fixture: two scored
    businesses, one `go_now` and one `nurture`, each with a firecrawl
    RawPayload holding a distinct `.test` address.
    """
    c1 = session.query(Business).filter_by(cid="c-1").one()
    c2 = session.query(Business).filter_by(cid="c-2").one()
    c1.website = "https://gonow.test"
    c2.website = "https://nurture.test"
    session.add(Score(business_id=c1.id, ruleset_version="hvac_v1",
                      fit_score=90, pain_score=90, quadrant="go_now",
                      coverage=0.8, reasons=[]))
    session.add(Score(business_id=c2.id, ruleset_version="hvac_v1",
                      fit_score=90, pain_score=20, quadrant="nurture",
                      coverage=0.8, reasons=[]))
    session.add(RawPayload(business_id=c1.id, source="firecrawl",
                           url="https://gonow.test/contact",
                           fetched_at=datetime(2026, 9, 1), payload={},
                           raw_text="<p>owner@gonow.test</p>"))
    session.add(RawPayload(business_id=c2.id, source="firecrawl",
                           url="https://nurture.test/contact",
                           fetched_at=datetime(2026, 9, 1), payload={},
                           raw_text="<p>owner@nurture.test</p>"))
    session.commit()

    r = client.post("/contacts/harvest", params={"quadrant": "nurture"})
    assert r.status_code == 200
    assert r.json()["businesses"] == 1
    # And the go_now business gained nothing.
    assert client.get("/leads/c-1").json()["contacts"] == []


@pytest.mark.parametrize("param", [
    "quadrant", "vertical", "state", "outcome_status",
    "min_fit", "min_pain", "ruleset_version",
])
def test_bulk_harvest_declares_every_lead_filter(param):
    """A filter FastAPI does not know about is silently discarded, so this
    checks the signature itself rather than a behaviour."""
    from app.api.routers.contacts import harvest_many
    assert param in inspect.signature(harvest_many).parameters
