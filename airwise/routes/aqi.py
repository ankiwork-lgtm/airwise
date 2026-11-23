"""Air quality lookup route."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Query, Request

from airwise.errors import ValidationFailure
from airwise.models import AirReading, ErrorResponse
from airwise.routes.limits import LimitCheck
from airwise.services import aqi as aqi_service

BOTH_SELECTORS_MESSAGE = "Provide either city or both lat and lon, not both."
NO_SELECTOR_MESSAGE = "Provide either city or both lat and lon."


def validate_location_params(city: str | None, lat: float | None, lon: float | None) -> None:
    """Require exactly one of ``city`` or the ``lat`` and ``lon`` pair."""
    has_coords = lat is not None and lon is not None
    if (city is not None) != has_coords and (lat is None) == (lon is None):
        return
    if city is not None and (lat is not None or lon is not None):
        raise ValidationFailure(BOTH_SELECTORS_MESSAGE, ["city", "lat", "lon"])
    fields = ["city"] if lat is None and lon is None else ["lat", "lon"]
    raise ValidationFailure(NO_SELECTOR_MESSAGE, fields)


def register_routes(
    app: FastAPI,
    get_http_client: Callable[[], Coroutine[Any, Any, httpx.AsyncClient]],
    limit_check: LimitCheck,
) -> None:
    """Register the route; ``get_http_client`` stays in ``main`` so tests can override it."""

    @app.get(
        "/api/aqi",
        response_model=AirReading,
        summary="Lookup current air quality",
        description="Return air reading and CPCB band for a city or coordinates.",
        tags=["Air Quality"],
        responses={
            404: {"model": ErrorResponse, "description": "City not found."},
            422: {
                "model": ErrorResponse,
                "description": "Invalid city or coordinate query parameters.",
            },
            429: {
                "model": ErrorResponse,
                "description": "Rate limit exceeded (30 requests/minute).",
            },
            502: {
                "model": ErrorResponse,
                "description": "Upstream air quality lookup unavailable.",
            },
        },
    )
    async def get_aqi(
        request: Request,
        city: str | None = None,
        lat: float | None = Query(default=None, ge=-90, le=90),
        lon: float | None = Query(default=None, ge=-180, le=180),
        client: httpx.AsyncClient = Depends(get_http_client),
    ) -> AirReading:
        """Return the current air reading for a city or a coordinate pair."""
        limit_check(request)
        validate_location_params(city, lat, lon)
        return await aqi_service.get_reading(client, city=city, lat=lat, lon=lon)
