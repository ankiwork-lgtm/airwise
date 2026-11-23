"""Exception handlers and the JSON error body shared by the whole app."""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from airwise.errors import AppError
from airwise.middleware import SECURITY_HEADERS

logger = logging.getLogger("airwise")
GENERIC_SERVER_ERROR_MESSAGE = "Internal server error."
VALIDATION_STATUS = 422
SERVER_ERROR_STATUS = 500
_NON_FIELD_LOC = ("body", "query", "path")


def error_body(code: str, message: str, fields: list[str] | None = None) -> dict[str, Any]:
    """Build the JSON error envelope: ``{"error": {"code", "message", "fields"}}``."""
    return {"error": {"code": code, "message": message, "fields": list(fields or [])}}


def _field_path(loc: tuple[Any, ...]) -> str:
    """Turn a pydantic error location into a dotted field name ("body" if there is none)."""
    parts = [str(p) for p in loc if p not in _NON_FIELD_LOC]
    return ".".join(parts) if parts else "body"


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render an ``AppError`` with its own status, code, fields and headers."""
    err = cast(AppError, exc)
    return JSONResponse(
        status_code=err.status,
        content=error_body(err.code, err.message, err.fields),
        headers=err.headers or None,
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render a request validation error, listing field names only."""
    err = cast(RequestValidationError, exc)
    # Build fields from `loc` only. Never echo `input` or `msg` values.
    fields: list[str] = []
    for error in err.errors():
        path = _field_path(tuple(error.get("loc", ())))
        if path not in fields:
            fields.append(path)
    return JSONResponse(
        status_code=VALIDATION_STATUS,
        content=error_body("validation_error", "Invalid request.", fields),
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render any other exception as a generic 500 that reveals nothing about the cause."""
    # Log only the exception class name: no message, traceback, or paths.
    logger.error("Unhandled exception: %s", type(exc).__name__)
    # Starlette's ServerErrorMiddleware sends this response outside the user middleware
    # stack, so SecurityHeadersMiddleware never sees it: set the headers here.
    return JSONResponse(
        status_code=SERVER_ERROR_STATUS,
        content=error_body("server_error", GENERIC_SERVER_ERROR_MESSAGE),
        headers={name.decode("ascii"): value.decode("ascii") for name, value in SECURITY_HEADERS},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install the handlers above on ``app``."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
