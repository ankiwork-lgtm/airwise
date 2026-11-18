"""Validation and endpoint tests for POST /api/plan (Property 7 for the plan route)."""
import json

from hypothesis import given, settings, strategies as st

from airwise.services.llm import PLAN_JSON_SCHEMA
from tests.strategies import profiles
from tests.test_aqi_endpoint import AQ_OK, GEO_OK, make_client, make_handler

MARKER = "ZZQQMARKER"

VALID_PROFILE = {
    "city": "Delhi",
    "kids": True,
    "elderly": False,
    "respiratory": True,
    "commute": "car",
    "cooking_fuel": "biomass",
    "heating": "none",
    "has_purifier": False,
    "ventilation": "mostly_closed",
}


class RecordingLLM:
    """Fake LLM client that records each call and builds a valid plan from the prompt."""

    def __init__(self, result=None):
        self.calls: list[dict] = []
        self._result = result

    async def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        if self._result is not None:
            return self._result
        table = json.loads(kwargs["user"])["data"]["impact_table"]
        ids = [row["id"] for row in table]

        def item(i):
            return {
                "text": f"Action {i}",
                "why_it_matters": "Reduces exposure.",
                "impact_id": ids[0] if ids and i == 0 else None,
                "context_factor": None,
            }

        return {
            "routine": {s: [item(0)] for s in ("morning", "commute", "midday", "evening")},
            "indoor_hacks": [item(1)],
            "swaps": [item(2)],
            "vulnerable_note": "Children and respiratory patients should take extra care.",
        }


def _client(calls, llm=None):
    c = make_client(make_handler(geocode=GEO_OK, aq=AQ_OK, calls=calls))
    from airwise.main import get_llm_client

    c.app.dependency_overrides[get_llm_client] = lambda: llm or RecordingLLM()
    return c


# ---------------------------------------------------------------- examples


def test_valid_llm_response_has_full_single_response_shape(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    llm = RecordingLLM()
    calls: list[str] = []
    with _client(calls, llm) as c:
        r = c.post("/api/plan", json={"profile": VALID_PROFILE})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"plan", "reading"}
    plan = body["plan"]
    assert plan["fallback"] is False
    assert plan["estimated"] is False
    assert set(plan) == {
        "routine", "indoor_hacks", "swaps", "vulnerable_note",
        "impact_table", "exposure_score", "fallback", "estimated",
    }
    assert set(plan["routine"]) == {"morning", "commute", "midday", "evening"}
    assert plan["impact_table"], "profile should yield impact rows"
    assert body["reading"]["source"] == "live"
    assert body["reading"]["location_name"] == "Delhi"
    assert len(llm.calls) == 1


def test_llm_request_carries_table_ids_and_json_schema_format(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    llm = RecordingLLM()
    with _client([], llm) as c:
        r = c.post("/api/plan", json={"profile": VALID_PROFILE})
    assert r.status_code == 200
    assert len(llm.calls) == 1
    call = llm.calls[0]
    table_ids = [row["id"] for row in r.json()["plan"]["impact_table"]]
    prompt_ids = [row["id"] for row in json.loads(call["user"])["data"]["impact_table"]]
    assert table_ids and prompt_ids == table_ids
    assert call["schema"] == PLAN_JSON_SCHEMA
    assert call["schema_name"]
    # The first item that cites a table id keeps the server-owned figures.
    cited = r.json()["plan"]["routine"]["morning"][0]
    assert cited["impact_id"] == table_ids[0]
    assert cited["impact"] is not None


def test_openai_client_sends_json_schema_response_format(monkeypatch):
    """Through the real OpenAIClient (SDK stubbed), the request uses a strict json_schema format."""
    from types import SimpleNamespace

    from airwise.services import llm as llm_module

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    seen = {}
    inner = RecordingLLM()

    class FakeCompletions:
        async def create(self, **kwargs):
            seen.update(kwargs)
            data = await inner.complete_json(user=kwargs["messages"][1]["content"])
            msg = SimpleNamespace(content=json.dumps(data))
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_module, "AsyncOpenAI", FakeAsyncOpenAI)
    from airwise.main import get_llm_client

    c = make_client(make_handler(geocode=GEO_OK, aq=AQ_OK))
    c.app.dependency_overrides[get_llm_client] = llm_module.OpenAIClient
    with c:
        r = c.post("/api/plan", json={"profile": VALID_PROFILE})
    assert r.status_code == 200
    assert r.json()["plan"]["fallback"] is False
    fmt = seen["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == PLAN_JSON_SCHEMA


def test_out_of_range_latitude_names_field_and_skips_aqi_service():
    calls: list[str] = []
    llm = RecordingLLM()
    with _client(calls, llm) as c:
        r = c.post(
            "/api/plan",
            json={"profile": VALID_PROFILE, "latitude": 91, "longitude": 77.2},
        )
    assert r.status_code == 422
    assert "latitude" in r.json()["error"]["fields"]
    assert calls == []
    assert llm.calls == []


def test_out_of_range_longitude_names_field_and_skips_aqi_service():
    calls: list[str] = []
    with _client(calls) as c:
        r = c.post(
            "/api/plan",
            json={"profile": VALID_PROFILE, "latitude": 28.6, "longitude": -181},
        )
    assert r.status_code == 422
    assert "longitude" in r.json()["error"]["fields"]
    assert calls == []


# ---------------------------------------------------------------- Property 7

_FINITE = dict(allow_nan=False, allow_infinity=False)

_bad_city = st.one_of(
    st.just(""),
    st.text(alphabet=" \t", min_size=1, max_size=5),
    st.just("x" * 101),
    st.integers(),
    st.lists(st.integers(), max_size=2),
)
_bad_bool = st.one_of(st.just(MARKER), st.lists(st.integers(), max_size=2), st.dictionaries(st.just("a"), st.integers(), max_size=1))
_bad_enum = st.text(min_size=1, max_size=20).map(lambda s: MARKER + s)
_bad_lat = st.one_of(
    st.floats(min_value=90.0001, max_value=1e6, **_FINITE),
    st.floats(min_value=-1e6, max_value=-90.0001, **_FINITE),
)
_bad_lon = st.one_of(
    st.floats(min_value=180.0001, max_value=1e6, **_FINITE),
    st.floats(min_value=-1e6, max_value=-180.0001, **_FINITE),
)
_extra_key = st.text(alphabet="abcdefghij_", min_size=3, max_size=10).filter(
    lambda k: k not in {"profile", "latitude", "longitude"}
)

_PROFILE_BOOLS = ["kids", "elderly", "respiratory", "has_purifier"]
_PROFILE_ENUMS = ["commute", "cooking_fuel", "heating", "ventilation"]

# Each case produces (payload, expected field names that must appear in the error).
@st.composite
def invalid_payloads(draw):
    profile = draw(profiles()).model_dump(mode="json")
    payload: dict = {"profile": profile}
    kind = draw(
        st.sampled_from(
            ["city", "bool", "enum", "missing", "profile_extra", "top_extra", "lat", "lon", "lat_only", "lon_only"]
        )
    )
    if kind == "city":
        payload["profile"]["city"] = draw(_bad_city)
        return payload, ["profile.city"]
    if kind == "bool":
        f = draw(st.sampled_from(_PROFILE_BOOLS))
        payload["profile"][f] = draw(_bad_bool)
        return payload, [f"profile.{f}"]
    if kind == "enum":
        f = draw(st.sampled_from(_PROFILE_ENUMS))
        payload["profile"][f] = draw(_bad_enum)
        return payload, [f"profile.{f}"]
    if kind == "missing":
        f = draw(st.sampled_from(["city", *_PROFILE_BOOLS, *_PROFILE_ENUMS]))
        del payload["profile"][f]
        return payload, [f"profile.{f}"]
    if kind == "profile_extra":
        k = draw(_extra_key)
        payload["profile"][k] = 1
        return payload, [f"profile.{k}"]
    if kind == "top_extra":
        k = draw(_extra_key)
        payload[k] = 1
        return payload, [k]
    if kind == "lat":
        payload["latitude"] = draw(_bad_lat)
        payload["longitude"] = draw(st.floats(min_value=-180, max_value=180, **_FINITE))
        return payload, ["latitude"]
    if kind == "lon":
        payload["latitude"] = draw(st.floats(min_value=-90, max_value=90, **_FINITE))
        payload["longitude"] = draw(_bad_lon)
        return payload, ["longitude"]
    if kind == "lat_only":
        payload["latitude"] = draw(st.floats(min_value=-90, max_value=90, **_FINITE))
        return payload, ["body"]
    payload["longitude"] = draw(st.floats(min_value=-180, max_value=180, **_FINITE))
    return payload, ["body"]


# Feature: airwise, Property 7: Invalid payloads are rejected with the offending fields
# **Validates: Requirements 4.2, 4.3, 9.1, 9.3, 9.4, 9.5**
@settings(max_examples=100, deadline=None)
@given(case=invalid_payloads())
def test_property_invalid_plan_payloads_rejected_with_fields(case):
    payload, expected = case
    calls: list[str] = []
    llm = RecordingLLM()
    with _client(calls, llm) as c:
        r = c.post("/api/plan", json=payload)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    for field in expected:
        assert field in err["fields"]
    # Rejected before any AQI_Service call or LLM call.
    assert calls == []
    assert llm.calls == []
    # Submitted values are never echoed back.
    assert MARKER not in r.text
