"""Endpoint tests for GET /api/aqi and the coordinate validation property."""

import httpx
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from airwise.config import AQ_URL, GEOCODE_URL
from airwise.main import create_app, get_http_client


def make_handler(*, geocode=None, aq=None, calls=None):
    """Build a MockTransport handler. geocode/aq are dicts (JSON), ints (status) or exceptions."""

    def respond(spec, request):
        if isinstance(spec, Exception):
            raise spec
        if isinstance(spec, int):
            return httpx.Response(spec, json={})
        return httpx.Response(200, json=spec)

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        url = str(request.url)
        if url.startswith(GEOCODE_URL):
            return respond(geocode, request)
        if url.startswith(AQ_URL):
            return respond(aq, request)
        raise AssertionError(f"unexpected url {url}")

    return handler


def make_client(handler) -> TestClient:
    app = create_app()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def override():
        return http

    app.dependency_overrides[get_http_client] = override
    return TestClient(app)


GEO_OK = {"results": [{"name": "Delhi", "latitude": 28.6, "longitude": 77.2}]}
AQ_OK = {"current": {"pm2_5": 100.0, "pm10": 200.0}}


def test_valid_city_returns_live_reading():
    with make_client(make_handler(geocode=GEO_OK, aq=AQ_OK)) as c:
        r = c.get("/api/aqi", params={"city": "Delhi"})
    assert r.status_code == 200
    body = r.json()
    assert body["location_name"] == "Delhi"
    assert body["source"] == "live"
    assert body["latitude"] == 28.6 and body["longitude"] == 77.2
    assert body["band"] == "Poor"


def test_valid_coordinates_skip_geocoding():
    calls: list[str] = []
    with make_client(make_handler(aq=AQ_OK, calls=calls)) as c:
        r = c.get("/api/aqi", params={"lat": 19.07, "lon": 72.87})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "live"
    assert body["location_name"] == "Your location"
    assert all(u.startswith(AQ_URL) for u in calls)


def test_city_not_found_returns_404():
    with make_client(make_handler(geocode={"results": []})) as c:
        r = c.get("/api/aqi", params={"city": "Nowhereville"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "city_not_found"


def test_geocoder_failure_returns_502():
    with make_client(make_handler(geocode=500)) as c:
        r = c.get("/api/aqi", params={"city": "Delhi"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "lookup_unavailable"


def test_geocoder_network_error_returns_502():
    with make_client(make_handler(geocode=httpx.ConnectError("down"))) as c:
        r = c.get("/api/aqi", params={"city": "Delhi"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "lookup_unavailable"


def test_air_quality_failure_falls_back_to_estimate():
    with make_client(make_handler(geocode=GEO_OK, aq=503)) as c:
        r = c.get("/api/aqi", params={"city": "Delhi"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "estimated"
    assert body["location_name"] == "Delhi"


def test_city_with_coordinates_rejected():
    calls: list[str] = []
    with make_client(make_handler(geocode=GEO_OK, aq=AQ_OK, calls=calls)) as c:
        r = c.get("/api/aqi", params={"city": "Delhi", "lat": 1, "lon": 2})
    assert r.status_code == 422
    assert {"city", "lat", "lon"} <= set(r.json()["error"]["fields"])
    assert calls == []


def test_only_lat_rejected():
    calls: list[str] = []
    with make_client(make_handler(aq=AQ_OK, calls=calls)) as c:
        r = c.get("/api/aqi", params={"lat": 10})
    assert r.status_code == 422
    assert "lon" in r.json()["error"]["fields"]
    assert calls == []


def test_only_lon_rejected():
    with make_client(make_handler(aq=AQ_OK)) as c:
        r = c.get("/api/aqi", params={"lon": 10})
    assert r.status_code == 422
    assert "lat" in r.json()["error"]["fields"]


def test_no_parameters_rejected():
    calls: list[str] = []
    with make_client(make_handler(calls=calls)) as c:
        r = c.get("/api/aqi")
    assert r.status_code == 422
    assert "city" in r.json()["error"]["fields"]
    assert calls == []


def test_non_numeric_lat_rejected_naming_field():
    with make_client(make_handler(aq=AQ_OK)) as c:
        r = c.get("/api/aqi", params={"lat": "abc", "lon": 10})
    assert r.status_code == 422
    assert "lat" in r.json()["error"]["fields"]


# Feature: airwise, Property 5: Coordinate validation
# **Validates: Requirements 2.3**
finite = dict(allow_nan=False, allow_infinity=False)
bad_lat = st.one_of(
    st.floats(min_value=90.0001, max_value=1e6, **finite),
    st.floats(min_value=-1e6, max_value=-90.0001, **finite),
)
bad_lon = st.one_of(
    st.floats(min_value=180.0001, max_value=1e6, **finite),
    st.floats(min_value=-1e6, max_value=-180.0001, **finite),
)
good_lat = st.floats(min_value=-90, max_value=90, **finite)
good_lon = st.floats(min_value=-180, max_value=180, **finite)
non_numeric = st.text(alphabet="xyzXYZ!@#", min_size=1, max_size=8)


@settings(max_examples=100, deadline=None)
@given(lat=good_lat, lon=good_lon)
def test_property_valid_coordinates_accepted(lat, lon):
    calls: list[str] = []
    with make_client(make_handler(aq=AQ_OK, calls=calls)) as c:
        r = c.get("/api/aqi", params={"lat": lat, "lon": lon})
    assert r.status_code == 200
    assert len(calls) == 1


@settings(max_examples=100, deadline=None)
@given(
    data=st.one_of(
        st.tuples(st.just("lat"), st.one_of(bad_lat, non_numeric), good_lon),
        st.tuples(st.just("lon"), good_lat, st.one_of(bad_lon, non_numeric)),
    )
)
def test_property_invalid_coordinates_rejected(data):
    bad_field, lat, lon = data
    calls: list[str] = []
    with make_client(make_handler(aq=AQ_OK, calls=calls)) as c:
        r = c.get("/api/aqi", params={"lat": lat, "lon": lon})
    assert r.status_code == 422
    assert bad_field in r.json()["error"]["fields"]
    assert calls == []


@settings(max_examples=100, deadline=None)
@given(lat=good_lat, lon=good_lon, missing=st.sampled_from(["lat", "lon"]))
def test_property_missing_coordinate_rejected(lat, lon, missing):
    params = {"lat": lat, "lon": lon}
    del params[missing]
    calls: list[str] = []
    with make_client(make_handler(aq=AQ_OK, calls=calls)) as c:
        r = c.get("/api/aqi", params=params)
    assert r.status_code == 422
    assert missing in r.json()["error"]["fields"]
    assert calls == []
