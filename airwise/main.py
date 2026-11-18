"""FastAPI application factory, health route, index route, and error handlers."""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse

from airwise.config import (
    CHAT_LIMIT,
    OPEN_METEO_TIMEOUT_S,
    PLAN_LIMIT,
    REQUEST_DEADLINE_S,
    WINDOW_S,
    Deadline,
)
from airwise.errors import AppError, RateLimited, ValidationFailure
from airwise.middleware import BodySizeLimitMiddleware, client_ip
from airwise.ratelimit import FixedWindowLimiter
from airwise.models import (
    AirReading,
    ChatReply,
    ChatRequest,
    PlanRequest,
    PlanResponse,
)
from airwise.services import aqi as aqi_service
from airwise.services.chat import answer as chat_answer
from airwise.services.llm import LLMClient, OpenAIClient
from airwise.services.plan import generate_plan

INDEX_PATH = Path(__file__).resolve().parent.parent / "public" / "index.html"

logger = logging.getLogger("airwise")
GENERIC_SERVER_ERROR_MESSAGE = "Internal server error."


_client: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    """Shared AsyncClient; override via app.dependency_overrides in tests."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=OPEN_METEO_TIMEOUT_S)
    return _client


def get_llm_client() -> LLMClient:
    """LLM client; override via app.dependency_overrides in tests."""
    return OpenAIClient()


def get_deadline() -> Deadline:
    """Fresh per-request time budget."""
    return Deadline(REQUEST_DEADLINE_S)


def error_body(code: str, message: str, fields: list[str] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "fields": list(fields or [])}}


def _field_path(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) if parts else "body"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=error_body(exc.code, exc.message, exc.fields),
        headers=exc.headers or None,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Build fields from `loc` only. Never echo `input` or `msg` values.
    fields: list[str] = []
    for err in exc.errors():
        path = _field_path(tuple(err.get("loc", ())))
        if path not in fields:
            fields.append(path)
    return JSONResponse(
        status_code=422,
        content=error_body("validation_error", "Invalid request.", fields),
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log only the exception class name: no message, traceback, or paths.
    logger.error("Unhandled exception: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=error_body("server_error", GENERIC_SERVER_ERROR_MESSAGE),
    )


def _rate_limit_check(endpoint: str, limiter: FixedWindowLimiter):
    def check(request: Request) -> None:
        decision = limiter.check(f"{endpoint}:{client_ip(request)}")
        if not decision.allowed:
            raise RateLimited(decision.retry_after)

    return check


def create_app() -> FastAPI:
    app = FastAPI(title="AirWise")
    plan_limiter = FixedWindowLimiter(PLAN_LIMIT, WINDOW_S)
    chat_limiter = FixedWindowLimiter(CHAT_LIMIT, WINDOW_S)
    app.state.plan_limiter = plan_limiter
    app.state.chat_limiter = chat_limiter
    plan_limit_check = _rate_limit_check("plan", plan_limiter)
    chat_limit_check = _rate_limit_check("chat", chat_limiter)

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
    app.add_middleware(BodySizeLimitMiddleware)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/aqi", response_model=AirReading)
    async def get_aqi(
        city: str | None = None,
        lat: float | None = Query(default=None, ge=-90, le=90),
        lon: float | None = Query(default=None, ge=-180, le=180),
        client: httpx.AsyncClient = Depends(get_http_client),
    ) -> AirReading:
        has_coords = lat is not None and lon is not None
        if (city is not None) == has_coords or (lat is None) != (lon is None):
            if city is not None and (lat is not None or lon is not None):
                msg = "Provide either city or both lat and lon, not both."
                fields = ["city", "lat", "lon"]
            else:
                msg = "Provide either city or both lat and lon."
                fields = ["city"] if lat is None and lon is None else ["lat", "lon"]
            raise ValidationFailure(msg, fields)
        return await aqi_service.get_reading(client, city=city, lat=lat, lon=lon)

    @app.post("/api/plan", response_model=PlanResponse)
    async def post_plan(
        body: PlanRequest,
        request: Request,
        client: httpx.AsyncClient = Depends(get_http_client),
        llm: LLMClient = Depends(get_llm_client),
        deadline: Deadline = Depends(get_deadline),
    ) -> PlanResponse:
        plan_limit_check(request)
        profile = body.profile
        if body.latitude is not None and body.longitude is not None:
            reading = await aqi_service.get_reading(
                client, city=None, lat=body.latitude, lon=body.longitude
            )
            reading = reading.model_copy(update={"location_name": profile.city})
        else:
            reading = await aqi_service.get_reading(
                client, city=profile.city, lat=None, lon=None
            )
        plan = await generate_plan(profile, reading, llm=llm, deadline=deadline)
        return PlanResponse(plan=plan, reading=reading)

    @app.post("/api/chat", response_model=ChatReply)
    async def post_chat(
        body: ChatRequest,
        request: Request,
        llm: LLMClient = Depends(get_llm_client),
        deadline: Deadline = Depends(get_deadline),
    ) -> ChatReply:
        chat_limit_check(request)
        return await chat_answer(body, llm=llm, deadline=deadline)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(INDEX_PATH.read_text(encoding="utf-8"))

    return app


app = create_app()
