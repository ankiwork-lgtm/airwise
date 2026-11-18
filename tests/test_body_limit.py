"""Property 19: Body size limit."""
import asyncio
import json

from hypothesis import given, settings, strategies as st

from airwise.config import MAX_BODY_BYTES
from airwise.middleware import BodySizeLimitMiddleware


def _run(headers, chunks):
    """Drive the middleware with a stub app; return (route_calls, sent, body_seen)."""
    calls = []
    seen = []
    sent = []
    queue = list(chunks)

    async def app(scope, receive, send):
        calls.append(1)
        while True:
            msg = await receive()
            seen.append(msg.get("body", b""))
            if not msg.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        if not queue:
            return {"type": "http.disconnect"}
        body, more = queue.pop(0)
        return {"type": "http.request", "body": body, "more_body": more}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/plan", "headers": headers}
    asyncio.run(BodySizeLimitMiddleware(app)(scope, receive, send))
    return calls, sent, b"".join(seen)


def _split(total, parts):
    """Split `total` bytes into `parts` non-empty-ish chunks."""
    size = max(1, -(-total // parts))
    chunks = []
    remaining = total
    while remaining > 0:
        n = min(size, remaining)
        remaining -= n
        chunks.append((b"x" * n, remaining > 0))
    return chunks or [(b"", False)]


def _assert_413(calls, sent):
    assert calls == []
    assert sent[0]["status"] == 413
    body = json.loads(sent[1]["body"])
    assert body["error"]["code"] == "payload_too_large"


# Feature: airwise, Property 19: Body size limit
# **Validates: Requirements 9.2**
@settings(max_examples=100)
@given(size=st.integers(min_value=MAX_BODY_BYTES + 1, max_value=MAX_BODY_BYTES * 20))
def test_declared_content_length_over_limit_rejected(size):
    calls, sent, _ = _run([(b"content-length", str(size).encode())], [(b"", False)])
    _assert_413(calls, sent)


# Feature: airwise, Property 19: Body size limit
# **Validates: Requirements 9.2**
@settings(max_examples=100)
@given(
    total=st.integers(min_value=MAX_BODY_BYTES + 1, max_value=MAX_BODY_BYTES * 3),
    parts=st.integers(min_value=1, max_value=50),
)
def test_streamed_chunked_body_over_limit_rejected(total, parts):
    calls, sent, _ = _run([(b"transfer-encoding", b"chunked")], _split(total, parts))
    _assert_413(calls, sent)


# Feature: airwise, Property 19: Body size limit
# **Validates: Requirements 9.2**
@settings(max_examples=100)
@given(
    total=st.integers(min_value=0, max_value=MAX_BODY_BYTES),
    parts=st.integers(min_value=1, max_value=50),
    declared=st.booleans(),
)
def test_body_within_limit_passes_through(total, parts, declared):
    headers = [(b"content-length", str(total).encode())] if declared else []
    calls, sent, seen = _run(headers, _split(total, parts))
    assert calls == [1]
    assert sent[0]["status"] == 200
    assert len(seen) == total
