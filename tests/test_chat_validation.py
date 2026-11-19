"""Validation and endpoint tests for POST /api/chat (Properties 7 and 8 for the chat route)."""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st

from airwise.main import create_app, get_llm_client
from airwise.services.chat import (
    CHAT_FAILURE_MESSAGE,
    OFF_TOPIC_REPLY,
    SCOPE_DECLINE_REPLY,
)

MARKER = "ZZQQMARKER"

ITEM = {"text": "Wear a mask", "why_it_matters": "Filters particles."}
PLAN = {
    "routine": {s: [ITEM] for s in ("morning", "commute", "midday", "evening")},
    "indoor_hacks": [ITEM],
    "swaps": [ITEM],
    "vulnerable_note": "Take extra care.",
    "impact_table": [],
    "exposure_score": 55.0,
    "fallback": False,
    "estimated": False,
}
READING = {
    "location_name": "Delhi",
    "latitude": 28.6,
    "longitude": 77.2,
    "pm2_5": 120.0,
    "pm10": 200.0,
    "aqi": 300,
    "band": "Very Poor",
    "grap_stage": "Stage III",
    "source": "live",
}
PROFILE = {
    "city": "Delhi",
    "kids": True,
    "elderly": False,
    "respiratory": True,
    "commute": "car",
    "cooking_fuel": "lpg",
    "heating": "none",
    "has_purifier": False,
    "ventilation": "mostly_closed",
}
SAFE_MESSAGE = "How is the air today?"


def valid_payload(message: str = SAFE_MESSAGE, history: list | None = None) -> dict:
    return copy.deepcopy(
        {
            "message": message,
            "history": history or [],
            "plan": PLAN,
            "reading": READING,
            "profile": PROFILE,
        }
    )


class RecordingLLM:
    def __init__(self, result=None, exc: Exception | None = None):
        self.calls: list[dict] = []
        self._result = result
        self._exc = exc

    async def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        if self._result is not None:
            return self._result
        return {"reply": "The AQI is 300.", "on_topic": True, "discusses_health": False}


def _client(llm: RecordingLLM) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_llm_client] = lambda: llm
    return TestClient(app)


# ---------------------------------------------------------------- examples


def test_statelessness_same_request_same_llm_payload(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm = RecordingLLM()
    payload = valid_payload(history=[{"role": "user", "content": "Hi"}])
    with _client(llm) as c:
        r1 = c.post("/api/chat", json=payload)
        c.post("/api/chat", json=valid_payload("Something else entirely?"))
        r2 = c.post("/api/chat", json=payload)
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json() == {"reply": "The AQI is 300.", "failed": False}
    assert len(llm.calls) == 3
    assert llm.calls[0]["user"] == llm.calls[2]["user"]
    assert llm.calls[0]["system"] == llm.calls[2]["system"]
    assert llm.calls[0]["user"] != llm.calls[1]["user"]


def test_missing_key_returns_failure_message_without_llm_call():
    llm = RecordingLLM()
    with _client(llm) as c:
        r = c.post("/api/chat", json=valid_payload())
    assert r.status_code == 200
    assert r.json() == {"reply": CHAT_FAILURE_MESSAGE, "failed": True}
    assert llm.calls == []


def test_llm_error_returns_failure_message(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm = RecordingLLM(exc=RuntimeError("boom"))
    with _client(llm) as c:
        r = c.post("/api/chat", json=valid_payload())
    assert r.status_code == 200
    assert r.json() == {"reply": CHAT_FAILURE_MESSAGE, "failed": True}
    assert len(llm.calls) == 1


def test_llm_timeout_returns_failure_message(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm = RecordingLLM(exc=TimeoutError())
    with _client(llm) as c:
        r = c.post("/api/chat", json=valid_payload())
    assert r.status_code == 200
    assert r.json() == {"reply": CHAT_FAILURE_MESSAGE, "failed": True}
    assert len(llm.calls) == 1


def test_off_topic_message_gets_fixed_reply(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm = RecordingLLM({"reply": "Paris is the capital.", "on_topic": False, "discusses_health": False})
    with _client(llm) as c:
        r = c.post("/api/chat", json=valid_payload("What is the capital of France?"))
    assert r.status_code == 200
    assert r.json() == {"reply": OFF_TOPIC_REPLY, "failed": False}
    assert len(llm.calls) == 1


def test_out_of_scope_message_declined_without_llm_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm = RecordingLLM()
    with _client(llm) as c:
        r = c.post("/api/chat", json=valid_payload("Can you diagnose my cough?"))
    assert r.status_code == 200
    assert r.json() == {"reply": SCOPE_DECLINE_REPLY, "failed": False}
    assert llm.calls == []


# ---------------------------------------------------------------- Property 8

_TURN = {"role": "user", "content": "hello"}

_bad_messages = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n", min_size=1, max_size=20),
    st.integers(min_value=501, max_value=1500).map(lambda n: "x" * n),
)
_good_messages = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), max_codepoint=0x7F),
    min_size=1,
    max_size=500,
)


# Feature: airwise, Property 8: Chat message and history bounds
# **Validates: Requirements 8.6, 8.7**
@settings(max_examples=100, deadline=None)
@given(
    message=_bad_messages,
    history_len=st.integers(min_value=0, max_value=10),
)
def test_property_bad_message_rejected(message, history_len):
    llm = RecordingLLM()
    payload = valid_payload(message, [_TURN] * history_len)
    with _client(llm) as c:
        r = c.post("/api/chat", json=payload)
    assert r.status_code == 422
    assert "message" in r.json()["error"]["fields"]
    assert llm.calls == []


@settings(max_examples=100, deadline=None)
@given(history_len=st.integers(min_value=11, max_value=60), message=_good_messages)
def test_property_oversized_history_rejected(history_len, message):
    llm = RecordingLLM()
    payload = valid_payload(message, [_TURN] * history_len)
    with _client(llm) as c:
        r = c.post("/api/chat", json=payload)
    assert r.status_code == 422
    assert "history" in r.json()["error"]["fields"]
    assert llm.calls == []


@settings(max_examples=100, deadline=None)
@given(
    message=_good_messages,
    history=st.lists(
        st.fixed_dictionaries(
            {
                "role": st.sampled_from(["user", "assistant"]),
                "content": st.text(min_size=1, max_size=200),
            }
        ),
        max_size=10,
    ),
)
def test_property_in_bounds_message_and_history_pass_validation(message, history):
    llm = RecordingLLM()
    payload = valid_payload(message, history)
    with _client(llm) as c:
        r = c.post("/api/chat", json=payload)
    assert r.status_code == 200
    assert set(r.json()) == {"reply", "failed"}


# ---------------------------------------------------------------- Property 7 (chat route)

_bad_enum = st.text(min_size=1, max_size=20).map(lambda s: MARKER + s)
_extra_key = st.text(alphabet="abcdefghij_", min_size=3, max_size=10).filter(
    lambda k: k not in {"message", "history", "plan", "reading", "profile"}
)
_PROFILE_ENUMS = ["commute", "cooking_fuel", "heating", "ventilation"]
_PROFILE_BOOLS = ["kids", "elderly", "respiratory", "has_purifier"]


@st.composite
def invalid_chat_payloads(draw):
    p = valid_payload()
    kind = draw(
        st.sampled_from(
            [
                "message_long",
                "turn_content_long",
                "turn_bad_role",
                "history_over_50",
                "plan_list_over_50",
                "plan_missing",
                "plan_extra",
                "plan_text_long",
                "reading_aqi",
                "reading_band",
                "reading_lat",
                "reading_missing",
                "profile_enum",
                "profile_bool",
                "profile_city_long",
                "profile_missing",
                "profile_extra",
                "top_extra",
                "top_missing",
            ]
        )
    )
    if kind == "message_long":
        p["message"] = "m" * draw(st.integers(501, 5000))
        return p, ["message"]
    if kind == "turn_content_long":
        p["history"] = [{"role": "user", "content": "c" * draw(st.integers(2001, 4000))}]
        return p, ["history.0.content"]
    if kind == "turn_bad_role":
        p["history"] = [{"role": draw(_bad_enum), "content": "hi"}]
        return p, ["history.0.role"]
    if kind == "history_over_50":
        p["history"] = [_TURN] * draw(st.integers(51, 120))
        return p, ["history"]
    if kind == "plan_list_over_50":
        key = draw(st.sampled_from(["indoor_hacks", "swaps", "impact_table"]))
        if key == "impact_table":
            row = {
                "id": "a", "action": "a", "basis": "b", "source_note": "s",
                "exposure_reduction_pct": 1.0, "co2_kg_per_day": 1.0, "approximate": True,
            }
            p["plan"][key] = [row] * draw(st.integers(51, 100))
        else:
            p["plan"][key] = [ITEM] * draw(st.integers(51, 100))
        return p, [f"plan.{key}"]
    if kind == "plan_missing":
        f = draw(st.sampled_from(list(PLAN)))
        del p["plan"][f]
        return p, [f"plan.{f}"]
    if kind == "plan_extra":
        k = draw(_extra_key)
        p["plan"][k] = 1
        return p, [f"plan.{k}"]
    if kind == "plan_text_long":
        p["plan"]["indoor_hacks"] = [{"text": "t" * draw(st.integers(301, 600)), "why_it_matters": "w"}]
        return p, ["plan.indoor_hacks.0.text"]
    if kind == "reading_aqi":
        p["reading"]["aqi"] = draw(st.one_of(st.integers(501, 10**6), st.integers(-10**6, -1)))
        return p, ["reading.aqi"]
    if kind == "reading_band":
        p["reading"]["band"] = draw(_bad_enum)
        return p, ["reading.band"]
    if kind == "reading_lat":
        p["reading"]["latitude"] = draw(st.floats(90.0001, 1e6, allow_nan=False))
        return p, ["reading.latitude"]
    if kind == "reading_missing":
        f = draw(st.sampled_from(["location_name", "latitude", "longitude", "aqi", "band", "grap_stage", "source"]))
        del p["reading"][f]
        return p, [f"reading.{f}"]
    if kind == "profile_enum":
        f = draw(st.sampled_from(_PROFILE_ENUMS))
        p["profile"][f] = draw(_bad_enum)
        return p, [f"profile.{f}"]
    if kind == "profile_bool":
        f = draw(st.sampled_from(_PROFILE_BOOLS))
        p["profile"][f] = MARKER
        return p, [f"profile.{f}"]
    if kind == "profile_city_long":
        p["profile"]["city"] = "x" * draw(st.integers(101, 300))
        return p, ["profile.city"]
    if kind == "profile_missing":
        f = draw(st.sampled_from(["city", *_PROFILE_BOOLS, *_PROFILE_ENUMS]))
        del p["profile"][f]
        return p, [f"profile.{f}"]
    if kind == "profile_extra":
        k = draw(_extra_key)
        p["profile"][k] = 1
        return p, [f"profile.{k}"]
    if kind == "top_extra":
        k = draw(_extra_key)
        p[k] = 1
        return p, [k]
    f = draw(st.sampled_from(["message", "plan", "reading", "profile"]))
    del p[f]
    return p, [f]


# Feature: airwise, Property 7: Invalid payloads are rejected with the offending fields
# **Validates: Requirements 4.3, 9.1, 9.3, 9.4, 9.5**
@settings(max_examples=100, deadline=None)
@given(case=invalid_chat_payloads())
def test_property_invalid_chat_payloads_rejected_with_fields(case):
    payload, expected = case
    llm = RecordingLLM()
    with _client(llm) as c:
        r = c.post("/api/chat", json=payload)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    for field in expected:
        assert field in err["fields"]
    assert llm.calls == []
    assert MARKER not in r.text
