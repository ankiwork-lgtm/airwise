"""Pure ASGI middleware: request body size limit and security response headers."""

from __future__ import annotations

import ipaddress
import json

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from airwise.config import MAX_BODY_BYTES
from airwise.errors import PayloadTooLarge

# Strict CSP: same-origin only, no inline script/style, no 'unsafe-*' (the page loads only
# /app.js and /app.css and calls only /api/...). Mirrored in vercel.json; tests keep them equal.
CSP_DIRECTIVES: tuple[str, ...] = (
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self'",
    "connect-src 'self'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
)
CONTENT_SECURITY_POLICY = "; ".join(CSP_DIRECTIVES)

# Single source of truth for the security headers (T3.5 mirrors these in vercel.json).
# HSTS is left to the TLS terminator.
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    # Stop browsers MIME-sniffing a response into an executable type.
    (b"X-Content-Type-Options", b"nosniff"),
    # Never leak the page URL to other origins via the Referer header.
    (b"Referrer-Policy", b"no-referrer"),
    # Forbid framing the app (clickjacking).
    (b"X-Frame-Options", b"DENY"),
    # Geolocation stays on for our own origin ("Use my location"); other powerful features off.
    (
        b"Permissions-Policy",
        b"geolocation=(self), camera=(), microphone=(), payment=(), usb=()",
    ),
    # Isolate the browsing context group from cross-origin windows.
    (b"Cross-Origin-Opener-Policy", b"same-origin"),
    # Content-Security-Policy (frame-ancestors duplicates X-Frame-Options for modern browsers).
    (b"Content-Security-Policy", CONTENT_SECURITY_POLICY.encode("ascii")),
)


def client_ip(request: Request) -> str:
    """First valid X-Forwarded-For entry, else the socket peer, else "unknown"."""
    header = request.headers.get("x-forwarded-for")
    if header:
        candidate = header.split(",")[0].strip()
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            pass
        else:
            # ip_address() accepts IPv6 scope ids ("fe80::1%anything"); never use those as keys.
            if "%" not in candidate:
                return candidate
    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"


async def _send_413(send: Send) -> None:
    """Send the 413 JSON error response."""
    payload = json.dumps(
        {
            "error": {
                "code": PayloadTooLarge.code,
                "message": "Request body exceeds the 64 KB size limit.",
                "fields": [],
            }
        }
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": PayloadTooLarge.status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class BodySizeLimitMiddleware:
    """Reject bodies over MAX_BODY_BYTES with 413 before the route runs.

    A declared Content-Length over the limit is rejected immediately. Without a
    valid Content-Length (chunked), the body is read and counted up to the
    limit, then replayed to the app; exceeding it yields 413 and the app is
    never invoked.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        """Wrap ``app`` and reject bodies larger than ``max_bytes``."""
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI call, answering 413 when the body is too large."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared: int | None = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break

        if declared is not None:
            if declared > self.max_bytes:
                await _send_413(send)
                return
            await self.app(scope, receive, send)
            return

        # No usable Content-Length: count streamed bytes before invoking the app.
        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                # Client disconnected; hand it through unchanged.
                messages.append(message)
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await _send_413(send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break

        replay = iter(messages)

        async def replay_receive() -> Message:
            try:
                return next(replay)
            except StopIteration:
                return await receive()

        await self.app(scope, replay_receive, send)


class SecurityHeadersMiddleware:
    """Set SECURITY_HEADERS on every HTTP response, replacing same-named headers."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI call, adding the security headers to the response."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                names = {name.lower() for name, _ in SECURITY_HEADERS}
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names]
                headers.extend(SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
