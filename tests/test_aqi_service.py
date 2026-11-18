"""AQI service tests with httpx.MockTransport (no network, no API key)."""
import asyncio

import httpx
import pytest
from hypothesis import given, settings, strategies as st

from airwise.config import AQ_URL, GEOCODE_URL
from airwise.errors import CityNotFound, InvalidCity, LookupUnavailable
from airwise.services.aqi import get_reading

GEO_OK = {"results": [{"name": "Delhi", "latitude": 28.65, "longitude": 77.23}]}


def run(handler, **kwargs):
    """Run get_reading against a mock transport; return (outcome, requests)."""
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request):
        seen.append(request)
        return handler(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(wrapped)) as client:
            return await get_reading(client, **kwargs)

    try:
        return asyncio.run(go()), seen
    except Exception as exc:  # noqa: BLE001 - returned for assertions
        return exc, seen


def is_geo(request):
    return str(request.url).startswith(GEOCODE_URL)


def is_aq(request):
    return str(request.url).startswith(AQ_URL)


def make_handler(aq):
    """Geocoding succeeds; `aq` is a callable or response for the AQ request."""

    def handler(request):
        if is_geo(request):
            return httpx.Response(200, json=GEO_OK)
        return aq(request) if callable(aq) else aq

    return handler


def city_kwargs(city="Delhi"):
    return dict(city=city, lat=None, lon=None)


# Feature: airwise, Property 4: City name validation
# **Validates: Requirements 1.9**
@settings(max_examples=100, deadline=None)
@given(
    st.one_of(
        st.just(""),
        st.text(alphabet=" \t\n\r", max_size=20),
        st.text(alphabet=st.characters(blacklist_categories=("Cs", "Z", "Cc")), min_size=101, max_size=150),
    )
)
def test_property_invalid_city_rejected_without_http(city):
    out, seen = run(lambda r: httpx.Response(500), **city_kwargs(city))
    assert isinstance(out, InvalidCity)
    assert seen == []


# Feature: airwise, Property 4: City name validation
# **Validates: Requirements 1.9**
@settings(max_examples=100, deadline=None)
@given(
    st.text(alphabet=st.characters(blacklist_categories=("Cs", "Z", "Cc")), min_size=1, max_size=100),
    st.text(alphabet=" \t", max_size=5),
)
def test_property_valid_city_reaches_geocoding(city, pad):
    out, seen = run(lambda r: httpx.Response(200, json={}), **city_kwargs(pad + city + pad))
    assert isinstance(out, CityNotFound)
    assert len(seen) == 1 and is_geo(seen[0])


def test_geocode_request_parameters_and_timeouts():
    out, seen = run(make_handler(httpx.Response(200, json={"current": {"pm2_5": 40, "pm10": 80}})),
                    **city_kwargs())
    assert out.source == "live"
    geo, aq = seen
    p = geo.url.params
    assert p["count"] == "1" and p["countryCode"] == "IN" and p["name"] == "Delhi"
    assert set(geo.extensions["timeout"].values()) == {8.0}
    assert aq.url.params["current"] == "pm2_5,pm10"
    assert set(aq.extensions["timeout"].values()) == {8.0}


def test_no_results_is_city_not_found_with_no_aq_request():
    out, seen = run(lambda r: httpx.Response(200, json={"generationtime_ms": 1}), **city_kwargs())
    assert isinstance(out, CityNotFound)
    assert len(seen) == 1 and is_geo(seen[0])


def _raise(exc):
    def h(request):
        raise exc

    return h


@pytest.mark.parametrize(
    "handler",
    [
        _raise(httpx.ReadTimeout("t")),
        lambda r: httpx.Response(500),
        _raise(httpx.ConnectError("boom")),
    ],
    ids=["timeout", "500", "transport"],
)
def test_geocoding_failure_is_lookup_unavailable(handler):
    out, seen = run(handler, **city_kwargs())
    assert isinstance(out, LookupUnavailable)
    assert len(seen) == 1 and is_geo(seen[0])


@pytest.mark.parametrize(
    "aq",
    [
        _raise(httpx.ReadTimeout("t")),
        httpx.Response(500),
        httpx.Response(200, content=b"not json{"),
        httpx.Response(200, json={"current": {"pm2_5": None, "pm10": None}}),
    ],
    ids=["timeout", "500", "malformed", "both-null"],
)
def test_aq_failure_gives_estimated_reading_single_attempt(aq):
    out, seen = run(make_handler(aq), **city_kwargs())
    assert out.source == "estimated"
    assert [is_aq(r) for r in seen].count(True) == 1


@pytest.mark.parametrize(
    "current", [{"pm2_5": 40, "pm10": None}, {"pm2_5": None, "pm10": 120}, {"pm2_5": 40, "pm10": 120}]
)
def test_at_least_one_value_is_live(current):
    out, seen = run(make_handler(httpx.Response(200, json={"current": current})), **city_kwargs())
    assert out.source == "live"
    assert len([r for r in seen if is_aq(r)]) == 1


@pytest.mark.parametrize("city", ["", "   ", "x" * 101])
def test_invalid_city_examples_make_no_http_call(city):
    out, seen = run(lambda r: httpx.Response(200, json=GEO_OK), **city_kwargs(city))
    assert isinstance(out, InvalidCity)
    assert seen == []
