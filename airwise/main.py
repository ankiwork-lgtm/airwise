"""FastAPI application factory, health route, index route, and error handlers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from airwise.config import (
    AQI_LIMIT,
    CHAT_LIMIT,
    OPEN_METEO_TIMEOUT_S,
    PLAN_LIMIT,
    REQUEST_DEADLINE_S,
    WINDOW_S,
    Deadline,
    load_env_file,
)
from airwise.errors import AppError, RateLimited, ValidationFailure
from airwise.middleware import (
    SECURITY_HEADERS,
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    client_ip,
)
from airwise.models import (
    AirReading,
    ChatReply,
    ChatRequest,
    PlanRequest,
    PlanResponse,
)
from airwise.ratelimit import FixedWindowLimiter
from airwise.services import aqi as aqi_service
from airwise.services.chat import answer as chat_answer
from airwise.services.llm import AnthropicClient, LLMClient, aclose_llm_client
from airwise.services.plan import generate_plan

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
INDEX_PATH = PUBLIC_DIR / "index.html"
CSS_PATH = PUBLIC_DIR / "app.css"
JS_PATH = PUBLIC_DIR / "app.js"

logger = logging.getLogger("airwise")
GENERIC_SERVER_ERROR_MESSAGE = "Internal server error."


# An AsyncClient is bound to the event loop it first runs in, so the loop is stored with it.
_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


async def get_http_client() -> httpx.AsyncClient:
    """Shared AsyncClient; override via app.dependency_overrides in tests."""
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    # The running loop is never closed, so a stored loop that is not this one is either
    # another live loop or a closed one: drop its client (it cannot be awaited from here).
    if _client is None or _client_loop is not loop:
        _client = httpx.AsyncClient(timeout=OPEN_METEO_TIMEOUT_S)
        _client_loop = loop
    return _client


async def aclose_http_client() -> None:
    """Close and forget the shared client, if any. Safe to call repeatedly."""
    global _client, _client_loop
    client, loop = _client, _client_loop
    _client = _client_loop = None
    if client is not None and loop is asyncio.get_running_loop():
        await client.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Close the shared HTTP clients on shutdown; nothing to do on startup (clients are lazy).

    The clients are process-wide, so shutting down any app (e.g. one per test) closes the
    shared ones. That is safe because both accessors recreate them lazily on next use.
    On Vercel the serverless process may be frozen without ever running this shutdown,
    which is harmless: it exists for uvicorn/container shutdowns and tests.
    """
    try:
        yield
    finally:
        # Isolated so one failing close cannot skip the other or mask the original error.
        # Log the exception class only (no message), and let CancelledError and other
        # BaseExceptions propagate.
        for name, close in (
            ("open-meteo", aclose_http_client),
            ("llm", aclose_llm_client),
        ):
            try:
                await close()
            except Exception as exc:
                logger.warning("Failed to close %s client: %s", name, type(exc).__name__)


def get_llm_client() -> LLMClient:
    """LLM client; override via app.dependency_overrides in tests."""
    return AnthropicClient()


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


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
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
    # Starlette's ServerErrorMiddleware sends this response outside the user middleware
    # stack, so SecurityHeadersMiddleware never sees it: set the headers here.
    return JSONResponse(
        status_code=500,
        content=error_body("server_error", GENERIC_SERVER_ERROR_MESSAGE),
        headers={name.decode("ascii"): value.decode("ascii") for name, value in SECURITY_HEADERS},
    )


def _rate_limit_check(endpoint: str, limiter: FixedWindowLimiter):
    def check(request: Request) -> None:
        decision = limiter.check(f"{endpoint}:{client_ip(request)}")
        if not decision.allowed:
            raise RateLimited(decision.retry_after)

    return check


def create_app() -> FastAPI:
    load_env_file()
    app = FastAPI(title="AirWise", lifespan=lifespan)
    plan_limiter = FixedWindowLimiter(PLAN_LIMIT, WINDOW_S)
    chat_limiter = FixedWindowLimiter(CHAT_LIMIT, WINDOW_S)
    aqi_limiter = FixedWindowLimiter(AQI_LIMIT, WINDOW_S)
    app.state.plan_limiter = plan_limiter
    app.state.chat_limiter = chat_limiter
    app.state.aqi_limiter = aqi_limiter
    plan_limit_check = _rate_limit_check("plan", plan_limiter)
    chat_limit_check = _rate_limit_check("chat", chat_limiter)
    aqi_limit_check = _rate_limit_check("aqi", aqi_limiter)

    # Starlette types handlers as (Request, Exception) but only calls each one for the
    # exception class it is registered with, so the narrower `exc` type is safe.
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        validation_error_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, unexpected_error_handler)
    app.add_middleware(BodySizeLimitMiddleware)
    # Added last, so outermost among user middleware: also covers the 413s sent above.
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/aqi", response_model=AirReading)
    async def get_aqi(
        request: Request,
        city: str | None = None,
        lat: float | None = Query(default=None, ge=-90, le=90),
        lon: float | None = Query(default=None, ge=-180, le=180),
        client: httpx.AsyncClient = Depends(get_http_client),
    ) -> AirReading:
        aqi_limit_check(request)
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
            reading = await aqi_service.get_reading(client, city=profile.city, lat=None, lon=None)
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
    async def index() -> FileResponse:
        return FileResponse(INDEX_PATH, media_type="text/html; charset=utf-8")

    # Vercel serves public/ statically in production; these two routes keep
    # local `uvicorn` working without exposing the rest of the directory.
    @app.get("/app.css", include_in_schema=False)
    async def app_css() -> FileResponse:
        return FileResponse(CSS_PATH, media_type="text/css; charset=utf-8")

    @app.get("/app.js", include_in_schema=False)
    async def app_js() -> FileResponse:
        return FileResponse(JS_PATH, media_type="text/javascript; charset=utf-8")

    # No icon is shipped; answer browsers' automatic request with an empty 204, not a 404.
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204, headers={"Cache-Control": "public, max-age=86400"})

    return app


app = create_app()
