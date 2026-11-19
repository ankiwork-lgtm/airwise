"""Property and endpoint tests for the rate limiter and client IP extraction."""
from __future__ import annotations

import ipaddress
from types import SimpleNamespace

from hypothesis import given, settings, strategies as st

from airwise.main import create_app, get_llm_client
from airwise.middleware import client_ip
from airwise.ratelimit import FixedWindowLimiter
from tests.test_chat_validation import RecordingLLM as ChatLLM, valid_payload
from tests.test_aqi_endpoint import AQ_OK, GEO_OK, make_client, make_handler
from tests.test_plan_validation import VALID_PROFILE, RecordingLLM as PlanLLM

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
        ep: FixedWindowLimiter(limit, WINDOW, clock=lambda: now[0])
        for ep, limit in LIMITS.items()
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
