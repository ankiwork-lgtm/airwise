"""Per-endpoint rate limit check shared by the routers."""

from __future__ import annotations

from collections.abc import Callable

from starlette.requests import Request

from airwise.errors import RateLimited
from airwise.middleware import client_ip
from airwise.ratelimit import FixedWindowLimiter

LimitCheck = Callable[[Request], None]


def rate_limit_check(endpoint: str, limiter: FixedWindowLimiter) -> LimitCheck:
    """Return a check that raises ``RateLimited`` once the caller exceeds ``limiter``."""

    def check(request: Request) -> None:
        decision = limiter.check(f"{endpoint}:{client_ip(request)}")
        if not decision.allowed:
            raise RateLimited(decision.retry_after)

    return check
