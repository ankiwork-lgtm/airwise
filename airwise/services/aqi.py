"""AQI computation: CPCB India AQI, band and indicative GRAP stage."""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from datetime import UTC, datetime
from typing import Any, Literal, NamedTuple

import httpx

from airwise.config import (
    AQ_SOURCE_URL,
    AQ_URL,
    ESTIMATED_PM10,
    ESTIMATED_PM25,
    GEOCODE_URL,
    LOOKUP_CACHE_MAX_ENTRIES,
    LOOKUP_CACHE_TTL_S,
    OPEN_METEO_TIMEOUT_S,
)
from airwise.errors import CityNotFound, InvalidCity, LookupUnavailable
from airwise.models import AirReading, CPCBBand, GrapStage


class Breakpoint(NamedTuple):
    bp_lo: float
    bp_hi: float
    i_lo: int
    i_hi: int


PM25_BREAKPOINTS: list[Breakpoint] = [
    Breakpoint(0, 30, 0, 50),
    Breakpoint(31, 60, 51, 100),
    Breakpoint(61, 90, 101, 200),
    Breakpoint(91, 120, 201, 300),
    Breakpoint(121, 250, 301, 400),
    Breakpoint(251, 380, 401, 500),
]

PM10_BREAKPOINTS: list[Breakpoint] = [
    Breakpoint(0, 50, 0, 50),
    Breakpoint(51, 100, 51, 100),
    Breakpoint(101, 250, 101, 200),
    Breakpoint(251, 350, 201, 300),
    Breakpoint(351, 430, 301, 400),
    Breakpoint(431, 510, 401, 500),
]


def sub_index(conc: float, table: list[Breakpoint]) -> float:
    """Piecewise-linear sub-index. Gap values take the next range's low index;
    values above the top range give 500."""
    for bp in table:
        if conc <= bp.bp_hi:
            if conc <= bp.bp_lo:
                return float(bp.i_lo)
            return (bp.i_hi - bp.i_lo) / (bp.bp_hi - bp.bp_lo) * (conc - bp.bp_lo) + bp.i_lo
    return 500.0


def compute_aqi(pm25: float | None, pm10: float | None) -> int:
    """Maximum of the available sub-indices, rounded and capped at 500."""
    subs: list[float] = []
    if pm25 is not None:
        subs.append(sub_index(pm25, PM25_BREAKPOINTS))
    if pm10 is not None:
        subs.append(sub_index(pm10, PM10_BREAKPOINTS))
    if not subs:
        raise ValueError("at least one of pm25 or pm10 is required")
    return min(500, round(max(subs)))


def band_for(aqi: int) -> CPCBBand:
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Satisfactory"
    if aqi <= 200:
        return "Moderate"
    if aqi <= 300:
        return "Poor"
    if aqi <= 400:
        return "Very Poor"
    return "Severe"


def grap_for(aqi: int) -> GrapStage:
    if aqi <= 200:
        return "none"
    if aqi <= 300:
        return "Stage I"
    if aqi <= 400:
        return "Stage II"
    if aqi <= 450:
        return "Stage III"
    return "Stage IV"


class Place(NamedTuple):
    name: str
    latitude: float
    longitude: float


_clock: Callable[[], float] = time.monotonic  # tests patch this


class _TTLCache[V]:
    """Tiny in-memory TTL cache. Values must be immutable (they are shared with callers).

    Every entry has the same TTL, so insertion order is also expiry order: expired entries
    sit at the front and the front is the oldest entry to evict when the cache is full.
    """

    def __init__(self) -> None:
        self._items: dict[Hashable, tuple[float, V]] = {}

    def get(self, key: Hashable) -> V | None:
        item = self._items.get(key)
        if item is None or item[0] <= _clock():
            self._items.pop(key, None)
            return None
        return item[1]

    def put(self, key: Hashable, value: V) -> None:
        now = _clock()
        self._items.pop(key, None)  # re-insert at the end
        while self._items:
            oldest = next(iter(self._items))
            if self._items[oldest][0] <= now or len(self._items) >= LOOKUP_CACHE_MAX_ENTRIES:
                del self._items[oldest]
            else:
                break
        self._items[key] = (now + LOOKUP_CACHE_TTL_S, value)

    def clear(self) -> None:
        self._items.clear()


_PM = tuple[float | None, float | None, str | None]  # pm2_5, pm10, observation time (UTC ISO)
_places: _TTLCache[Place] = _TTLCache()
_pm_readings: _TTLCache[_PM] = _TTLCache()


def clear_cache() -> None:
    """Drop all cached geocode and PM lookups (used by tests)."""
    _places.clear()
    _pm_readings.clear()


def _num(value: Any) -> float | None:
    """Return a finite, in-range PM value or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v != v or v < 0 or v > 5000:
        return None
    return v


def _observed_at(value: Any) -> str | None:
    """Normalise the upstream observation time to UTC ISO 8601, or None if unusable.

    Open-Meteo returns GMT times without an offset (e.g. "2025-01-15T09:00")."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build(
    name: str,
    lat: float,
    lon: float,
    pm25: float | None,
    pm10: float | None,
    source: Literal["live", "estimated"],
    observed_at: str | None = None,
) -> AirReading:
    aqi = compute_aqi(pm25, pm10)
    return AirReading(
        location_name=name,
        latitude=lat,
        longitude=lon,
        pm2_5=pm25,
        pm10=pm10,
        aqi=aqi,
        band=band_for(aqi),
        grap_stage=grap_for(aqi),
        source=source,
        source_url=AQ_SOURCE_URL if source == "live" else None,
        observed_at=observed_at if source == "live" else None,
    )


def estimated_reading(name: str, lat: float | None, lon: float | None) -> AirReading:
    """Reading built from the configured typical values, flagged as estimated."""
    return _build(
        (name or "Unknown")[:100],
        lat if lat is not None else 0.0,
        lon if lon is not None else 0.0,
        ESTIMATED_PM25,
        ESTIMATED_PM10,
        "estimated",
    )


async def geocode(client: httpx.AsyncClient, city: str) -> Place:
    """Resolve a city to its top-ranked Indian match. Successful lookups are cached."""
    key = " ".join(city.split()).casefold()
    cached = _places.get(key)
    if cached is not None:
        return cached
    place = await _geocode_upstream(client, city)
    _places.put(key, place)
    return place


async def _geocode_upstream(client: httpx.AsyncClient, city: str) -> Place:
    params: dict[str, str | int] = {
        "name": city,
        "count": 1,
        "language": "en",
        "format": "json",
        "countryCode": "IN",
    }
    try:
        resp = await client.get(GEOCODE_URL, params=params, timeout=OPEN_METEO_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LookupUnavailable() from exc
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        raise CityNotFound()
    try:
        top = results[0]
        lat = float(top["latitude"])
        lon = float(top["longitude"])
        name = str(top.get("name") or city)[:100]
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise LookupUnavailable() from exc
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise LookupUnavailable()
    return Place(name, lat, lon)


async def fetch_pm(client: httpx.AsyncClient, lat: float, lon: float) -> _PM:
    """Fetch current PM2.5, PM10 and observation time. Raises httpx.HTTPError or ValueError
    on failure.

    Results are cached by coordinates rounded to 2 decimals (about 1 km); a result with
    no usable value is not cached."""
    key = (round(lat, 2), round(lon, 2))
    cached = _pm_readings.get(key)
    if cached is not None:
        return cached
    pm = await _fetch_pm_upstream(client, lat, lon)
    if pm[:2] != (None, None):
        _pm_readings.put(key, pm)
    return pm


async def _fetch_pm_upstream(client: httpx.AsyncClient, lat: float, lon: float) -> _PM:
    params: dict[str, str | float] = {"latitude": lat, "longitude": lon, "current": "pm2_5,pm10"}
    resp = await client.get(AQ_URL, params=params, timeout=OPEN_METEO_TIMEOUT_S)
    resp.raise_for_status()
    data = resp.json()
    current = data.get("current") if isinstance(data, dict) else None
    if not isinstance(current, dict):
        return None, None, None
    return _num(current.get("pm2_5")), _num(current.get("pm10")), _observed_at(current.get("time"))


async def get_reading(
    client: httpx.AsyncClient,
    *,
    city: str | None,
    lat: float | None,
    lon: float | None,
) -> AirReading:
    """Resolve the location, fetch PM values, and fall back to an estimate."""
    if city is not None:
        name = city.strip()
        if not 1 <= len(name) <= 100:
            raise InvalidCity()
        place = await geocode(client, name)
    elif lat is not None and lon is not None:
        place = Place("Your location", lat, lon)
    else:
        raise InvalidCity()
    try:
        pm25, pm10, observed_at = await fetch_pm(client, place.latitude, place.longitude)
    except (httpx.HTTPError, ValueError):
        return estimated_reading(place.name, place.latitude, place.longitude)
    if pm25 is None and pm10 is None:
        return estimated_reading(place.name, place.latitude, place.longitude)
    return _build(place.name, place.latitude, place.longitude, pm25, pm10, "live", observed_at)
