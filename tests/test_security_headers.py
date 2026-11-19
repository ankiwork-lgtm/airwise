"""T3.4/T3.7: every response carries the fixed security headers (incl. CSP), exactly once."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from airwise.config import MAX_BODY_BYTES
from airwise.main import create_app, get_http_client
from airwise.middleware import SECURITY_HEADERS, SecurityHeadersMiddleware

EXPECTED = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "permissions-policy": "geolocation=(self), camera=(), microphone=(), payment=(), usb=()",
    "cross-origin-opener-policy": "same-origin",
    "content-security-policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'"
    ),
}


def _assert_headers(response):
    for name, value in EXPECTED.items():
        assert response.headers.get_list(name) == [value], name
    assert "strict-transport-security" not in response.headers


def _boom_client() -> TestClient:
    app = create_app()

    async def boom():
        raise RuntimeError("kaboom")

    app.dependency_overrides[get_http_client] = boom
    return TestClient(app, raise_server_exceptions=False)


def test_constant_matches_exact_values():
    assert {k.decode().lower(): v.decode() for k, v in SECURITY_HEADERS} == EXPECTED


def test_health_has_headers(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    _assert_headers(r)


def test_html_index_has_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    _assert_headers(r)


def test_422_from_request_validation_has_headers(client):
    r = client.get("/api/aqi", params={"lat": 999, "lon": 0})
    assert r.status_code == 422
    _assert_headers(r)


def test_422_from_app_error_has_headers(client):
    r = client.get("/api/aqi", params={"lat": 1})
    assert r.status_code == 422
    _assert_headers(r)


def test_404_has_headers(client):
    r = client.get("/no/such/path")
    assert r.status_code == 404
    _assert_headers(r)


def test_429_has_headers():
    app = create_app()

    async def unused_client():
        # Dependencies resolve before the in-handler limiter check; the 429 never uses it.
        return None

    app.dependency_overrides[get_http_client] = unused_client
    with TestClient(app) as c:
        while app.state.aqi_limiter.check("aqi:testclient").allowed:
            pass
        r = c.get("/api/aqi", params={"city": "Delhi"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    _assert_headers(r)


def test_413_from_body_limit_has_headers(client):
    r = client.post("/api/plan", content=b"x" * (MAX_BODY_BYTES + 1))
    assert r.status_code == 413
    _assert_headers(r)


def test_500_from_generic_handler_has_headers():
    with _boom_client() as c:
        r = c.get("/api/aqi", params={"city": "Delhi"})
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "server_error"
    _assert_headers(r)


def test_no_duplicate_headers_on_any_response(client):
    responses = [
        client.get("/api/health"),
        client.get("/"),
        client.get("/nope"),
        client.get("/api/aqi"),
        client.post("/api/plan", content=b"x" * (MAX_BODY_BYTES + 1)),
    ]
    with _boom_client() as c:
        responses.append(c.get("/api/aqi", params={"city": "Delhi"}))
    names = [name for name, _ in SECURITY_HEADERS]
    for r in responses:
        raw = [k.lower() for k, _ in r.headers.raw]
        for name in names:
            assert raw.count(name.lower()) == 1, (r.status_code, name)


def test_permissions_policy_keeps_geolocation_for_self():
    policy = EXPECTED["permissions-policy"]
    assert "geolocation=(self)" in policy
    assert "geolocation=()" not in policy


def _drive(scope, downstream_headers=()):
    sent = []

    async def app(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": 200, "headers": list(downstream_headers)}
        )
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(SecurityHeadersMiddleware(app)(scope, receive, send))
    return sent


def test_middleware_replaces_existing_header_instead_of_duplicating():
    sent = _drive(
        {"type": "http", "method": "GET", "path": "/", "headers": []},
        [(b"x-frame-options", b"SAMEORIGIN"), (b"content-type", b"text/plain")],
    )
    headers = sent[0]["headers"]
    frame = [v for k, v in headers if k.lower() == b"x-frame-options"]
    assert frame == [b"DENY"]
    assert (b"content-type", b"text/plain") in headers
    for name, value in SECURITY_HEADERS:
        assert [v for k, v in headers if k.lower() == name.lower()] == [value]
    assert sent[1] == {"type": "http.response.body", "body": b"ok"}


@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
def test_middleware_passes_non_http_scopes_through_untouched(scope_type):
    seen = []

    async def app(scope, receive, send):
        seen.append((scope, receive, send))

    async def receive():
        return {}

    async def send(message):
        raise AssertionError("must not send")

    scope = {"type": scope_type}
    asyncio.run(SecurityHeadersMiddleware(app)(scope, receive, send))
    assert seen == [(scope, receive, send)]
