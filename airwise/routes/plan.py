"""Plan generation route."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Request

from airwise.config import Deadline
from airwise.models import ErrorResponse, PlanRequest, PlanResponse
from airwise.routes.limits import LimitCheck
from airwise.services import aqi as aqi_service
from airwise.services.llm import LLMClient
from airwise.services.plan import generate_plan


def register_routes(
    app: FastAPI,
    get_http_client: Callable[[], Coroutine[Any, Any, httpx.AsyncClient]],
    get_llm_client: Callable[[], LLMClient],
    get_deadline: Callable[[], Deadline],
    limit_check: LimitCheck,
) -> None:
    """Register the route; the dependency functions stay in ``main`` so tests can override them."""

    @app.post(
        "/api/plan",
        response_model=PlanResponse,
        summary="Generate personalized routine plan",
        description="Generate daily routine and impact table tailored to household profile.",
        tags=["Plan Generation"],
        responses={
            413: {"model": ErrorResponse, "description": "Request body is too large (> 64 KB)."},
            422: {
                "model": ErrorResponse,
                "description": "Validation failure for profile or coordinates.",
            },
            429: {
                "model": ErrorResponse,
                "description": "Rate limit exceeded (10 requests/minute).",
            },
            502: {"model": ErrorResponse, "description": "Location lookup unavailable."},
        },
    )
    async def post_plan(
        body: PlanRequest,
        request: Request,
        client: httpx.AsyncClient = Depends(get_http_client),
        llm: LLMClient = Depends(get_llm_client),
        deadline: Deadline = Depends(get_deadline),
    ) -> PlanResponse:
        """Generate a plan for the household and the air reading at its location."""
        limit_check(request)
        profile = body.profile
        if body.latitude is not None and body.longitude is not None:
            reading = await aqi_service.get_reading(
                client, city=None, lat=body.latitude, lon=body.longitude
            )
            reading = reading.model_copy(update={"location_name": profile.city})
        else:
            reading = await aqi_service.get_reading(client, city=profile.city, lat=None, lon=None)
        plan = await generate_plan(profile, reading, llm=llm, deadline=deadline)
        return PlanResponse(plan=plan, reading=reading)
