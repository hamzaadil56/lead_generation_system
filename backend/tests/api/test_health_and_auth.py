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


def test_a_protected_route_rejects_a_non_ascii_key(client):
    """A non-ASCII header must fail closed, not crash `compare_digest`.

    `secrets.compare_digest` raises TypeError on non-ASCII str operands.
    Sent as raw bytes so httpx does not reject it client-side before it
    ever reaches the app.
    """
    client.headers.update({"X-API-Key": "café".encode("utf-8")})
    r = client.get("/runs")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid or missing API key"


def test_a_protected_route_rejects_an_empty_key(client):
    client.headers.update({"X-API-Key": ""})
    r = client.get("/runs")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid or missing API key"


def test_the_schema_and_docs_endpoints_are_not_served_at_all(anon_client):
    """I3: spec section 9 says FastAPI is "never publicly browsable", and
    `/openapi.json`, `/docs`, `/docs/oauth2-redirect` and `/redoc` were the
    one place that was untrue. All twelve data routes 401 correctly; these
    four returned 200 to an anonymous caller, handing over the complete
    route inventory, every request/response schema, and the field names of
    the internal DTOs. No data leaked, so this was exposure rather than
    compromise -- but it is the only exception to "everything except
    /health is authenticated", and the schema is the map for attacking the
    rest.

    They are disabled outright rather than gated on the API key. Swagger UI
    fetches `/openapi.json` from the browser with no way to attach the
    `X-API-Key` header, so "docs behind auth" is a broken page that still
    needs a second thing to go right; not registering the routes cannot be
    misconfigured. The single consumer is a Next.js server holding the key
    server-side, which needs the JSON contract at build time, not a
    browsable page in production.
    """
    for path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
        assert anon_client.get(path).status_code == 404, path


def test_every_registered_route_except_health_requires_an_api_key(anon_client):
    """Sweeps whatever is registered rather than a hand-written list, so a
    router added later cannot quietly ship unauthenticated (deferred item
    1). This is also what would have caught the docs endpoints above.
    """
    # Enumerated from the generated OpenAPI schema rather than a
    # hand-written list, so a router added later cannot quietly ship
    # unauthenticated. `app.openapi()` still builds in-process even though
    # the `/openapi.json` route is not served.
    schema = anon_client.app.openapi()

    checked = 0
    for path, operations in schema["paths"].items():
        if path == "/health":
            continue
        # Any value works: auth runs before the handler ever sees it.
        concrete = path.replace("{cid}", "c1").replace("{run_id}", "1")
        for method in operations:
            r = anon_client.request(method.upper(), concrete, json={})
            assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
            checked += 1

    assert checked >= 12, f"the sweep only reached {checked} routes"
