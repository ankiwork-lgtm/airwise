"""Tests for the coordinates path of POST /api/plan (latitude and longitude both given)."""

from __future__ import annotations

import httpx
import pytest

from airwise.config import AQ_URL, GEOCODE_URL
from airwise.main import get_llm_client
from airwise.models import PlanResponse
from tests.test_aqi_endpoint import AQ_OK, GEO_OK, make_client, make_handler
from tests.test_plan_validation import VALID_PROFILE, RecordingLLM

LAT, LON = 19.0760, 72.8777


def _client(calls: list[str], *, geocode=GEO_OK, aq=AQ_OK):
    c = make_client(make_handler(geocode=geocode, aq=aq, calls=calls))
    c.app.dependency_overrides[get_llm_client] = lambda: RecordingLLM()
    return c


def _aq_calls(calls: list[str]) -> list[str]:
    return [u for u in calls if u.startswith(AQ_URL)]


def _geo_calls(calls: list[str]) -> list[str]:
    return [u for u in calls if u.startswith(GEOCODE_URL)]


def _body(lat, lon, **profile):
    return {"profile": {**VALID_PROFILE, **profile}, "latitude": lat, "longitude": lon}


# ---------------------------------------------------------------- success path


def test_coordinates_use_air_quality_upstream_and_never_the_geocoder(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls: list[str] = []
    with _client(calls) as c:
        r = c.post("/api/plan", json=_body(LAT, LON, city="Mumbai"))
    assert r.status_code == 200
    assert _geo_calls(calls) == [], "the geocoder must not be called when coordinates are given"
    assert len(_aq_calls(calls)) == 1
    params = httpx.URL(_aq_calls(calls)[0]).params
    assert (float(params["latitude"]), float(params["longitude"])) == (LAT, LON)

    body = r.json()
    reading = body["reading"]
    assert reading["location_name"] == "Mumbai", "location_name is the profile city, not a label"
    assert (reading["latitude"], reading["longitude"]) == (LAT, LON)
    assert reading["source"] == "live"
    assert reading["pm2_5"] == 100.0 and reading["pm10"] == 200.0
    PlanResponse.model_validate(body)


@pytest.mark.parametrize("city", ["My location", "Nowhereville", "x" * 100, "  Delhi  "])
def test_city_is_only_a_label_when_coordinates_are_present(city):
    calls: list[str] = []
    # A geocoder that would reject every city: it must never be consulted.
    with _client(calls, geocode={"results": []}) as c:
        r = c.post("/api/plan", json=_body(LAT, LON, city=city))
    assert r.status_code == 200, r.text
    assert _geo_calls(calls) == []
    assert r.json()["reading"]["location_name"] == city.strip()


def test_city_is_only_a_label_even_when_the_geocoder_is_down():
    calls: list[str] = []
    with _client(calls, geocode=500) as c:
        r = c.post("/api/plan", json=_body(LAT, LON, city="My location"))
    assert r.status_code == 200
    assert _geo_calls(calls) == []


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (-90, -180),
        (90, 180),
        (-90.0, 180.0),
        (0, 0),
        (0.0, 0.0),
        (28, 77),
        (-89.99999999999999, 179.99999999999997),
        (28.613939123456789, 77.209021123456789),
    ],
)
def test_boundary_and_integer_coordinates_are_accepted(lat, lon):
    calls: list[str] = []
    with _client(calls) as c:
        r = c.post("/api/plan", json=_body(lat, lon))
    assert r.status_code == 200, r.text
    reading = r.json()["reading"]
    assert (reading["latitude"], reading["longitude"]) == (lat, lon)
    assert len(_aq_calls(calls)) == 1 and _geo_calls(calls) == []


# ------------------------------------------------------------ pair validation


@pytest.mark.parametrize(
    "extra",
    [
        {"latitude": LAT},
        {"longitude": LON},
        {"latitude": LAT, "longitude": None},
        {"latitude": None, "longitude": LON},
    ],
)
def test_only_one_of_the_pair_is_rejected_with_the_validation_envelope(extra):
    calls: list[str] = []
    llm = RecordingLLM()
    with _client(calls) as c:
        c.app.dependency_overrides[get_llm_client] = lambda: llm
        r = c.post("/api/plan", json={"profile": VALID_PROFILE, **extra})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation_error"
    # A model-level validator has loc ("body",), so the handler reports the whole body.
    assert error["fields"] == ["body"]
    assert "provided together" not in r.text, "the validator message must not be echoed"
    assert calls == [] and llm.calls == []


@pytest.mark.parametrize("extra", [{}, {"latitude": None, "longitude": None}])
def test_absent_and_explicit_null_coordinates_both_take_the_city_path(extra):
    calls: list[str] = []
    with _client(calls) as c:
        r = c.post("/api/plan", json={"profile": VALID_PROFILE, **extra})
    assert r.status_code == 200
    assert len(_geo_calls(calls)) == 1, "no coordinates: the city is geocoded"
    reading = r.json()["reading"]
    assert (reading["latitude"], reading["longitude"]) == (28.6, 77.2)  # from GEO_OK


# ------------------------------------------------------------ upstream failure


@pytest.mark.parametrize(
    "aq",
    [
        503,
        httpx.ConnectError("secret-host.internal refused"),
        httpx.ReadTimeout("slow"),
        {"current": {}},
        {"current": {"pm2_5": None, "pm10": None}},
        {"unexpected": "shape"},
    ],
    ids=["http-503", "connect-error", "timeout", "empty-current", "null-pm", "bad-shape"],
)
def test_air_quality_failure_falls_back_to_an_estimated_reading(aq):
    calls: list[str] = []
    with _client(calls, aq=aq) as c:
        r = c.post("/api/plan", json=_body(LAT, LON, city="Mumbai"))
    assert r.status_code == 200, r.text
    body = r.json()
    PlanResponse.model_validate(body)
    reading = body["reading"]
    assert reading["source"] == "estimated"
    assert reading["location_name"] == "Mumbai"
    assert (reading["latitude"], reading["longitude"]) == (LAT, LON)
    assert body["plan"]["estimated"] is True
    assert "secret-host" not in r.text and "Traceback" not in r.text
    assert _geo_calls(calls) == []


# ----------------------------------------------------------------- rate limits


def test_coordinates_requests_count_against_the_plan_limit_only(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with _client([]) as c:
        for _ in range(10):
            assert c.post("/api/plan", json=_body(LAT, LON)).status_code == 200
        r = c.post("/api/plan", json=_body(LAT, LON))
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "rate_limited"
        assert 1 <= int(r.headers["Retry-After"]) <= 60

        assert list(c.app.state.plan_limiter._state.values())[0][1] == 10
        assert c.app.state.aqi_limiter._state == {}, "plan requests must not consume the aqi quota"
        assert c.app.state.chat_limiter._state == {}, "plan requests must not consume chat quota"
        # The aqi endpoint is still fully available.
        assert c.get("/api/aqi", params={"lat": LAT, "lon": LON}).status_code == 200


# ------------------------------------------------------------------------ cache


def test_same_rounded_coordinates_call_the_air_quality_upstream_once():
    calls: list[str] = []
    with _client(calls) as c:
        first = c.post("/api/plan", json=_body(28.6101, 77.2001))
        # Same key after rounding to 2 decimals: (28.61, 77.2).
        second = c.post("/api/plan", json=_body(28.6149, 77.2049))
    assert first.status_code == second.status_code == 200
    assert len(_aq_calls(calls)) == 1, "the second request must be served from the cache"
    # The cache holds PM values only; each reading keeps its own request coordinates.
    assert first.json()["reading"]["latitude"] == 28.6101
    assert second.json()["reading"]["latitude"] == 28.6149


def test_different_coordinates_call_the_air_quality_upstream_twice():
    calls: list[str] = []
    with _client(calls) as c:
        assert c.post("/api/plan", json=_body(28.61, 77.20)).status_code == 200
        assert c.post("/api/plan", json=_body(19.08, 72.88)).status_code == 200
    assert len(_aq_calls(calls)) == 2


def test_failed_upstream_is_not_cached_so_a_later_request_retries():
    calls: list[str] = []
    with _client(calls, aq=503) as c:
        assert c.post("/api/plan", json=_body(LAT, LON)).status_code == 200
        assert c.post("/api/plan", json=_body(LAT, LON)).status_code == 200
    assert len(_aq_calls(calls)) == 2
