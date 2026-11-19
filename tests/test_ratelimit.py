"""Property and endpoint tests for the rate limiter and client IP extraction."""

from __future__ import annotations

import ipaddress
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from airwise.main import create_app, get_llm_client
from airwise.middleware import client_ip
from airwise.ratelimit import FixedWindowLimiter
from tests.test_aqi_endpoint import AQ_OK, GEO_OK, make_client, make_handler
from tests.test_chat_validation import RecordingLLM as ChatLLM
from tests.test_chat_validation import valid_payload
from tests.test_plan_validation import VALID_PROFILE
from tests.test_plan_validation import RecordingLLM as PlanLLM

WINDOW = 60.0
LIMITS = {"plan": 10, "chat": 30}

# ------------------------------------------------------------ Property 20

_requests = st.lists(
    st.tuples(
        st.one_of(
            st.sampled_from([0.0, 0.5, 59.0, 60.0, 61.0, 120.0]),
            st.floats(min_value=0, max_value=130, allow_nan=False),
        ),
        st.integers(min_value=0, max_value=2),
        st.sampled_from(["plan", "chat"]),
    ),
    max_size=150,
)


# Feature: airwise, Property 20: Fixed-window rate limiting
# **Validates: Requirements 10.1, 10.2, 10.3**
@settings(max_examples=200, deadline=None)
@given(seq=_requests)
def test_fixed_window_matches_reference_model(seq):
    now = [0.0]
    limiters = {
        ep: FixedWindowLimiter(limit, WINDOW, clock=lambda: now[0]) for ep, limit in LIMITS.items()
    }
    model: dict[tuple[int, str], list[float]] = {}  # (ip, ep) -> [start, count]
    for dt, ip, ep in seq:
        now[0] += dt
        decision = limiters[ep].check(f"{ep}:10.0.0.{ip}")

        entry = model.get((ip, ep))
        if entry is None or now[0] - entry[0] >= WINDOW:
            model[(ip, ep)] = [now[0], 1]
            expected = True
        elif entry[1] < LIMITS[ep]:
            entry[1] += 1
            expected = True
        else:
            expected = False  # rejection leaves the count unchanged

        assert decision.allowed == expected
        if not expected:
            assert 1 <= decision.retry_after <= 60
            assert decision.retry_after >= 1


# Feature: airwise, Property 20: Fixed-window rate limiting
# **Validates: Requirements 10.1, 10.2, 10.3**
@settings(max_examples=100, deadline=None)
@given(
    limit=st.integers(min_value=1, max_value=40),
    extra=st.integers(min_value=1, max_value=20),
    wait=st.floats(min_value=60, max_value=500, allow_nan=False),
)
def test_rejections_do_not_extend_window_and_next_window_allows(limit, extra, wait):
    now = [100.0]
    lim = FixedWindowLimiter(limit, WINDOW, clock=lambda: now[0])
    for _ in range(limit):
        assert lim.check("k").allowed
    for _ in range(extra):
        d = lim.check("k")
        assert not d.allowed and 1 <= d.retry_after <= 60
    now[0] += wait
    assert lim.check("k").allowed


# ------------------------------------------------------------ Property 21


def _req(header, host):
    headers = {} if header is None else {"x-forwarded-for": header}
    client = None if host is None else SimpleNamespace(host=host)
    return SimpleNamespace(headers=headers, client=client)


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


_ips = st.ip_addresses().map(str)
_ws = st.text(alphabet=" \t", max_size=3)
_invalid = st.text(max_size=20).filter(lambda s: not _is_ip(s.strip()) and "," not in s)
_tail = st.lists(st.text(alphabet="0123456789.:, abc", max_size=15), max_size=3).map(
    lambda xs: "".join("," + x for x in xs)
)
_hosts = st.one_of(st.none(), _ips)


# Feature: airwise, Property 21: Client IP extraction
# **Validates: Requirements 10.4, 10.5**
@settings(max_examples=100, deadline=None)
@given(first=_ips, pre=_ws, post=_ws, tail=_tail, host=_hosts)
def test_valid_first_entry_is_used(first, pre, post, tail, host):
    assert client_ip(_req(f"{pre}{first}{post}{tail}", host)) == first


# Feature: airwise, Property 21: Client IP extraction
# **Validates: Requirements 10.4, 10.5**
@settings(max_examples=100, deadline=None)
@given(first=_invalid, tail=_tail, host=_hosts, absent=st.booleans())
def test_invalid_empty_or_absent_header_uses_direct_address(first, tail, host, absent):
    header = None if absent else first + tail
    expected = host if host is not None else "unknown"
    assert client_ip(_req(header, host)) == expected


# ------------------------------------- X-Forwarded-For edge cases (T3.2)

_GARBAGE_FIRST_ENTRIES = [
    "not-an-ip",
    "999.1.1.1",
    "<script>",
    "",
    "a" * 10_000,
    "fe80::1%<script>",  # ipaddress accepts IPv6 scope ids; they must not become keys
    "::1%" + "a" * 500,
    "1.2.3.4%eth0",
]


@pytest.mark.parametrize("garbage", _GARBAGE_FIRST_ENTRIES)
def test_malformed_first_entry_falls_back_to_socket_peer_and_is_never_returned(garbage):
    assert client_ip(_req(garbage, "203.0.113.9")) == "203.0.113.9"
    assert client_ip(_req(garbage + ", 1.2.3.4", "203.0.113.9")) == "203.0.113.9"
    assert client_ip(_req(garbage, None)) == "unknown"


def test_valid_first_entry_wins_over_garbage_later_entries():
    header = "198.51.100.7, not-an-ip, <script>, 999.1.1.1"
    assert client_ip(_req(header, "203.0.113.9")) == "198.51.100.7"


def test_whitespace_around_first_entry_is_stripped():
    assert client_ip(_req("  \t198.51.100.7 \t , 10.0.0.1", "203.0.113.9")) == "198.51.100.7"


def test_ipv6_first_entry_is_accepted():
    assert client_ip(_req("2001:db8::1, 10.0.0.1", "203.0.113.9")) == "2001:db8::1"


def test_empty_first_entry_falls_back_and_later_entries_are_intentionally_ignored():
    assert client_ip(_req(", 1.2.3.4", "203.0.113.9")) == "203.0.113.9"
    assert client_ip(_req(", 1.2.3.4", None)) == "unknown"


# --------------------------------------------------------- endpoint examples


def _plan_client(llm):
    c = make_client(make_handler(geocode=GEO_OK, aq=AQ_OK, calls=[]))
    c.app.dependency_overrides[get_llm_client] = lambda: llm
    return c


def test_eleventh_plan_request_is_429_with_retry_after(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm = PlanLLM()
    with _plan_client(llm) as c:
        for _ in range(10):
            assert c.post("/api/plan", json={"profile": VALID_PROFILE}).status_code == 200
        r = c.post("/api/plan", json={"profile": VALID_PROFILE})
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert len(llm.calls) <= 10


def test_plan_and_chat_quotas_are_independent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    app = create_app()
    app.dependency_overrides[get_llm_client] = lambda: ChatLLM()
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        # Exhaust the plan quota with invalid (422) bodies? Those don't consume quota,
        # so drive the limiter state through the app's own plan limiter instead.
        for _ in range(10):
            assert app.state.plan_limiter.check("plan:testclient").allowed
        assert not app.state.plan_limiter.check("plan:testclient").allowed
        r = c.post("/api/chat", json=valid_payload())
        assert r.status_code == 200
        for _ in range(29):
            assert c.post("/api/chat", json=valid_payload()).status_code == 200
        r = c.post("/api/chat", json=valid_payload())
    assert r.status_code == 429
    assert "Retry-After" in r.headers


# ----------------------------------------------------------- /api/aqi limiter

AQI_PARAMS = {"lat": 28.6, "lon": 77.2}


def test_thirty_aqi_requests_allowed_then_429_with_retry_after():
    with make_client(make_handler(aq=AQ_OK)) as c:
        for _ in range(30):
            assert c.get("/api/aqi", params=AQI_PARAMS).status_code == 200
        r = c.get("/api/aqi", params=AQI_PARAMS)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(r.headers["Retry-After"]) <= 60


def test_aqi_limit_is_per_client_ip():
    blocked = {"X-Forwarded-For": "198.51.100.1"}
    other = {"X-Forwarded-For": "198.51.100.2"}
    with make_client(make_handler(aq=AQ_OK)) as c:
        for _ in range(30):
            assert c.get("/api/aqi", params=AQI_PARAMS, headers=blocked).status_code == 200
        assert c.get("/api/aqi", params=AQI_PARAMS, headers=blocked).status_code == 429
        assert c.get("/api/aqi", params=AQI_PARAMS, headers=other).status_code == 200


def test_forwarded_for_header_selects_the_rate_limit_bucket_documented_trust():
    # Documented trust assumption, not a feature: the first valid X-Forwarded-For entry
    # picks the bucket, so a client that can set the header itself bypasses the limit.
    # Safe only behind a proxy that sets/overwrites the header (see README, Known limits).
    with make_client(make_handler(aq=AQ_OK)) as c:
        for _ in range(30):
            assert c.get("/api/aqi", params=AQI_PARAMS).status_code == 200
        assert c.get("/api/aqi", params=AQI_PARAMS).status_code == 429
        spoofed = {"X-Forwarded-For": "192.0.2.77"}
        assert c.get("/api/aqi", params=AQI_PARAMS, headers=spoofed).status_code == 200
        # A garbage header does not pick a bucket: it falls back to the exhausted peer bucket.
        garbage = {"X-Forwarded-For": "fe80::1%<script>"}
        assert c.get("/api/aqi", params=AQI_PARAMS, headers=garbage).status_code == 429


def test_exhausted_aqi_quota_does_not_block_health_chat_or_plan(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with make_client(make_handler(geocode=GEO_OK, aq=AQ_OK)) as c:
        for _ in range(30):
            assert c.get("/api/aqi", params=AQI_PARAMS).status_code == 200
        assert c.get("/api/aqi", params=AQI_PARAMS).status_code == 429
        assert c.get("/api/health").status_code == 200
        c.app.dependency_overrides[get_llm_client] = lambda: ChatLLM()
        assert c.post("/api/chat", json=valid_payload()).status_code == 200
        c.app.dependency_overrides[get_llm_client] = lambda: PlanLLM()
        assert c.post("/api/plan", json={"profile": VALID_PROFILE}).status_code == 200


def test_malformed_aqi_params_return_422_without_consuming_quota():
    with make_client(make_handler(geocode=GEO_OK, aq=AQ_OK)) as c:
        for _ in range(35):
            r = c.get("/api/aqi", params={"lat": "abc", "lon": 10})
            assert r.status_code == 422
            assert r.json()["error"]["code"] == "validation_error"
        for _ in range(30):
            assert c.get("/api/aqi", params={"city": "Delhi"}).status_code == 200
        assert c.get("/api/aqi", params={"city": "Delhi"}).status_code == 429


def test_missing_aqi_params_return_422_and_count_toward_quota():
    # Missing city/coordinates is detected inside the handler, after the limit check.
    with make_client(make_handler(geocode=GEO_OK, aq=AQ_OK)) as c:
        for _ in range(30):
            r = c.get("/api/aqi")
            assert r.status_code == 422
            assert r.json()["error"]["code"] == "validation_error"
        assert c.get("/api/aqi", params={"city": "Delhi"}).status_code == 429
