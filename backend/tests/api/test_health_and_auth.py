def test_health_needs_no_api_key(anon_client):
    r = anon_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_a_protected_route_rejects_a_missing_key(anon_client):
    r = anon_client.get("/runs")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid or missing API key"


def test_a_protected_route_rejects_a_wrong_key(client):
    client.headers.update({"X-API-Key": "wrong"})
    assert client.get("/runs").status_code == 401


def test_a_protected_route_accepts_the_right_key(client):
    assert client.get("/runs").status_code == 200
