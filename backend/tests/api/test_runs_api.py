from app.models.run import Run


def test_post_runs_creates_a_queued_run_and_returns_it(client, session):
    r = client.post("/runs", json={"vertical": "hvac",
                                   "location": "Houston, TX", "pages": 2})

    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "queued"
    assert body["source"] == "ui"
    assert body["search_plan"]["location"] == "Houston, TX"
    assert session.query(Run).filter_by(id=body["id"]).one().status == "queued"


def test_post_runs_does_not_execute_the_run(client, session):
    """Execution belongs to the scheduler. A synchronous run would hold the
    connection open for minutes and time out behind any proxy."""
    from app.models.business import Business

    client.post("/runs", json={"vertical": "hvac", "location": "Houston, TX"})

    assert session.query(Business).count() == 0


def test_post_runs_rejects_a_plan_with_neither_state_nor_location(client):
    r = client.post("/runs", json={"vertical": "hvac"})
    assert r.status_code == 422


def test_post_runs_stores_the_cost_ceiling(client, session):
    r = client.post("/runs", json={"vertical": "hvac",
                                   "location": "Houston, TX",
                                   "max_cost_usd": 1.5})
    assert r.json()["max_cost_usd"] == 1.5


def test_post_runs_accepts_a_state_only_plan(client):
    """`config/locations.yaml` keys states lowercase (`tx`); a client typing
    the conventional uppercase abbreviation must not be rejected. Queuing
    only stores the plan (`build_search_plan` does the state lookup, and
    only runs at execution time), so this mainly guards against a
    regression that rejects `state` plans at creation time."""
    r = client.post("/runs", json={"vertical": "hvac", "state": "TX"})

    assert r.status_code == 201
    assert r.json()["search_plan"]["state"] == "TX"


def test_get_runs_returns_a_page_envelope(client):
    client.post("/runs", json={"vertical": "hvac", "location": "Houston, TX"})

    body = client.get("/runs").json()

    assert body["total"] == 1
    assert body["page"] == 1
    assert len(body["items"]) == 1


def test_get_runs_filters_by_status(client, session):
    client.post("/runs", json={"vertical": "hvac", "location": "Houston, TX"})
    session.query(Run).update({"status": "complete"})
    session.commit()

    assert client.get("/runs?status=complete").json()["total"] == 1
    assert client.get("/runs?status=queued").json()["total"] == 0


def test_get_run_by_id_returns_404_for_an_unknown_run(client):
    assert client.get("/runs/999999").status_code == 404


def test_get_run_by_id_returns_the_run(client):
    created = client.post("/runs", json={"vertical": "hvac",
                                         "location": "Houston, TX"}).json()

    r = client.get(f"/runs/{created['id']}")

    assert r.status_code == 200 and r.json()["id"] == created["id"]


def test_preview_returns_the_expansion_without_creating_a_run(client, session):
    r = client.post("/runs/preview", json={"vertical": "hvac",
                                           "state": "TX", "pages": 1})

    assert r.status_code == 200
    body = r.json()
    assert body["search_count"] == len(body["queries"]) > 0
    assert body["estimated_cost_usd"] > 0
    assert session.query(Run).count() == 0


def test_preview_rejects_an_unknown_vertical(client):
    r = client.post("/runs/preview", json={"vertical": "not_a_vertical",
                                           "location": "Houston, TX"})
    assert r.status_code in (400, 422)


def test_preview_rejects_an_unknown_state(client):
    """An unknown state reaches `build_search_plan`, which raises a
    `ValueError` -- caught by the app-level handler and rendered as 400, not
    an unhandled `KeyError` surfacing as a 500."""
    r = client.post("/runs/preview", json={"vertical": "hvac", "state": "ZZ"})
    assert r.status_code == 400


def test_preview_accepts_a_lowercase_or_mixed_case_state(client):
    lower = client.post("/runs/preview",
                        json={"vertical": "hvac", "state": "tx", "pages": 1})
    upper = client.post("/runs/preview",
                        json={"vertical": "hvac", "state": "TX", "pages": 1})

    assert lower.status_code == upper.status_code == 200
    assert lower.json()["queries"] == upper.json()["queries"]


def test_a_malformed_body_is_still_a_422_not_a_400(client):
    """FastAPI's own request-validation path must keep working after the
    app-level handler was narrowed to `SearchPlanError`. `pages` is
    bounded 1..20 by the schema, and that rejection is a
    `RequestValidationError` -- never routed through the 400 handler."""
    r = client.post("/runs", json={"vertical": "hvac",
                                   "location": "Houston, TX", "pages": 999})
    assert r.status_code == 422
