"""FastAPI application factory, shared client lifecycle, and static page routes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, HTMLResponse

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
from airwise.handlers import register_exception_handlers
from airwise.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from airwise.ratelimit import FixedWindowLimiter
from airwise.routes import aqi as aqi_routes
from airwise.routes import chat as chat_routes
from airwise.routes import health as health_routes
from airwise.routes import plan as plan_routes
from airwise.routes.limits import rate_limit_check
from airwise.services.llm import AnthropicClient, LLMClient, aclose_llm_client

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
INDEX_PATH = PUBLIC_DIR / "index.html"
CSS_PATH = PUBLIC_DIR / "app.css"
JS_PATH = PUBLIC_DIR / "app.js"

logger = logging.getLogger("airwise")


# An AsyncClient is bound to the event loop it first runs in, so the loop is stored with it.
_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


async def get_http_client() -> httpx.AsyncClient:
    """Shared AsyncClient; override via app.dependency_overrides in tests."""
    global _client, _client_loop  # noqa: PLW0603 - process-wide state, patched by tests
    loop = asyncio.get_running_loop()
    # The running loop is never closed, so a stored loop that is not this one is either
    # another live loop or a closed one: drop its client (it cannot be awaited from here).
    if _client is None or _client_loop is not loop:
        _client = httpx.AsyncClient(timeout=OPEN_METEO_TIMEOUT_S)
        _client_loop = loop
    return _client


async def aclose_http_client() -> None:
    """Close and forget the shared client, if any. Safe to call repeatedly."""
    global _client, _client_loop  # noqa: PLW0603 - process-wide state, patched by tests
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


def create_app() -> FastAPI:
    """Build the application: middleware, error handlers, API routes and static routes."""
    load_env_file()
    app = FastAPI(title="AirWise", lifespan=lifespan)
    plan_limiter = FixedWindowLimiter(PLAN_LIMIT, WINDOW_S)
    chat_limiter = FixedWindowLimiter(CHAT_LIMIT, WINDOW_S)
    aqi_limiter = FixedWindowLimiter(AQI_LIMIT, WINDOW_S)
    app.state.plan_limiter = plan_limiter
    app.state.chat_limiter = chat_limiter
    app.state.aqi_limiter = aqi_limiter

    register_exception_handlers(app)
    app.add_middleware(BodySizeLimitMiddleware)
    # Added last, so outermost among user middleware: also covers the 413s sent above.
    app.add_middleware(SecurityHeadersMiddleware)

    # The dependency functions live in this module so tests can override them by identity.
    health_routes.register_routes(app)
    aqi_routes.register_routes(app, get_http_client, rate_limit_check("aqi", aqi_limiter))
    plan_routes.register_routes(
        app, get_http_client, get_llm_client, get_deadline, rate_limit_check("plan", plan_limiter)
    )
    chat_routes.register_routes(
        app, get_llm_client, get_deadline, rate_limit_check("chat", chat_limiter)
    )
    _add_static_routes(app)
    return app


def _add_static_routes(app: FastAPI) -> None:
    """Serve the index page, assets and favicon (Vercel serves public/ itself in production)."""

    @app.get("/", response_class=HTMLResponse)
    async def index() -> FileResponse:
        """Serve the single-page UI."""
        return FileResponse(INDEX_PATH, media_type="text/html; charset=utf-8")

    # These two routes keep local `uvicorn` working without exposing the rest of the directory.
    @app.get("/app.css", include_in_schema=False)
    async def app_css() -> FileResponse:
        """Serve the stylesheet."""
        return FileResponse(CSS_PATH, media_type="text/css; charset=utf-8")

    @app.get("/app.js", include_in_schema=False)
    async def app_js() -> FileResponse:
        """Serve the client script."""
        return FileResponse(JS_PATH, media_type="text/javascript; charset=utf-8")

    # No icon is shipped; answer browsers' automatic request with an empty 204, not a 404.
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        """Answer the automatic favicon request with an empty 204."""
        return Response(status_code=204, headers={"Cache-Control": "public, max-age=86400"})


app = create_app()
