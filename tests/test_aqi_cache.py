"""TTL cache for geocode and PM lookups (mock transport, patched clock)."""

import asyncio

import httpx
import pytest

from airwise.config import AQ_URL, GEOCODE_URL, LOOKUP_CACHE_TTL_S
from airwise.errors import LookupUnavailable
from airwise.services import aqi
from airwise.services.aqi import clear_cache, get_reading

AQ_OK = {"current": {"pm2_5": 40, "pm10": 80}}


class Upstream:
    """Mock Open-Meteo that counts calls and can fail on demand."""

    def __init__(self):
        self.geo_calls = 0
        self.aq_calls = 0
        self.geo_fail = False
        self.aq_fail = False
        self.aq_body = AQ_OK

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(GEOCODE_URL):
            self.geo_calls += 1
            if self.geo_fail:
                return httpx.Response(500)
            name = request.url.params["name"]
            lat = 10.0 + len(name)  # distinct coordinates per distinct name length
            return httpx.Response(
                200, json={"results": [{"name": name, "latitude": lat, "longitude": 77.0}]}
            )
        assert url.startswith(AQ_URL)
        self.aq_calls += 1
        if self.aq_fail:
            return httpx.Response(500)
        return httpx.Response(200, json=self.aq_body)


def lookup(upstream, **kwargs):
    kwargs.setdefault("city", None)
    kwargs.setdefault("lat", None)
    kwargs.setdefault("lon", None)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            return await get_reading(client, **kwargs)

    return asyncio.run(go())


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(aqi, "_clock", lambda: now[0])
    return now


def test_repeated_city_lookup_calls_upstream_once():
    up = Upstream()
    first = lookup(up, city="Delhi")
    second = lookup(up, city="Delhi")
    assert first == second and first.source == "live"
    assert (up.geo_calls, up.aq_calls) == (1, 1)


def test_city_key_is_normalised():
    up = Upstream()
    lookup(up, city="New  Delhi")
    lookup(up, city="  new delhi ")
    lookup(up, city="NEW\tDELHI")
    assert (up.geo_calls, up.aq_calls) == (1, 1)


def test_repeated_coordinates_call_upstream_once_and_round_to_two_decimals():
    up = Upstream()
    lookup(up, lat=28.6139, lon=77.2090)
    lookup(up, lat=28.6141, lon=77.2093)  # same key after rounding
    assert (up.geo_calls, up.aq_calls) == (0, 1)
    lookup(up, lat=28.65, lon=77.2090)  # different key
    assert up.aq_calls == 2


def test_different_cities_and_coordinates_do_not_collide():
    up = Upstream()
    a = lookup(up, city="Pune")
    b = lookup(up, city="Mumbai")
    assert a.location_name == "Pune" and b.location_name == "Mumbai"
    assert up.geo_calls == 2 and up.aq_calls == 2
    c = lookup(up, lat=1.0, lon=2.0)
    d = lookup(up, lat=1.0, lon=3.0)
    assert (c.latitude, c.longitude) == (1.0, 2.0)
    assert (d.latitude, d.longitude) == (1.0, 3.0)
    assert up.aq_calls == 4


def test_entries_expire_after_ttl(clock):
    up = Upstream()
    lookup(up, city="Delhi")
    clock[0] += LOOKUP_CACHE_TTL_S - 1
    lookup(up, city="Delhi")
    assert (up.geo_calls, up.aq_calls) == (1, 1)
    clock[0] += 1  # exactly at the TTL: expired
    lookup(up, city="Delhi")
    assert (up.geo_calls, up.aq_calls) == (2, 2)


def test_geocode_failure_is_not_cached():
    up = Upstream()
    up.geo_fail = True
    for _ in range(2):
        with pytest.raises(LookupUnavailable):
            lookup(up, city="Delhi")
    assert up.geo_calls == 2
    up.geo_fail = False
    assert lookup(up, city="Delhi").source == "live"
    assert up.geo_calls == 3


def test_pm_failure_falls_back_and_is_not_cached():
    up = Upstream()
    up.aq_fail = True
    first = lookup(up, city="Delhi")
    assert first.source == "estimated"
    up.aq_fail = False
    second = lookup(up, city="Delhi")
    assert second.source == "live"
    assert (up.geo_calls, up.aq_calls) == (1, 2)  # place cached, failed PM retried


def test_empty_pm_result_is_not_cached():
    up = Upstream()
    up.aq_body = {"current": {"pm2_5": None, "pm10": None}}
    assert lookup(up, city="Delhi").source == "estimated"
    up.aq_body = AQ_OK
    assert lookup(up, city="Delhi").source == "live"
    assert up.aq_calls == 2


def test_size_cap_evicts_oldest(monkeypatch):
    monkeypatch.setattr(aqi, "LOOKUP_CACHE_MAX_ENTRIES", 2)
    up = Upstream()
    for city in ("a", "bb", "ccc"):  # "a" is the oldest and is evicted by "ccc"
        lookup(up, city=city)
    assert up.geo_calls == 3
    lookup(up, city="bb")
    lookup(up, city="ccc")
    assert up.geo_calls == 3  # still cached
    lookup(up, city="a")
    assert up.geo_calls == 4  # evicted, fetched again


def test_expired_entries_are_dropped_on_insert(clock):
    cache = aqi._TTLCache[int]()
    cache.put("old", 1)
    clock[0] += LOOKUP_CACHE_TTL_S
    cache.put("new", 2)
    assert list(cache._items) == ["new"]


def test_clear_cache_forces_new_upstream_call():
    up = Upstream()
    lookup(up, city="Delhi")
    clear_cache()
    lookup(up, city="Delhi")
    assert (up.geo_calls, up.aq_calls) == (2, 2)
