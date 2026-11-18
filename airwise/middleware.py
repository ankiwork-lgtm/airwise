"""Pure ASGI middleware: request body size limit."""
from __future__ import annotations

import ipaddress
import json

from airwise.config import MAX_BODY_BYTES
from airwise.errors import PayloadTooLarge


def client_ip(request) -> str:
    """First valid X-Forwarded-For entry, else the socket peer, else "unknown"."""
    header = request.headers.get("x-forwarded-for")
    if header:
        candidate = header.split(",")[0].strip()
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            pass
    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"


async def _send_413(send) -> None:
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

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
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
        messages: list[dict] = []
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

        async def replay_receive() -> dict:
            try:
                return next(replay)
            except StopIteration:
                return await receive()

        await self.app(scope, replay_receive, send)
