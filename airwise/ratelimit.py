"""In-memory fixed-window rate limiter with an injectable clock."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

CLEANUP_THRESHOLD = 10_000


@dataclass(frozen=True)
class Decision:
    """Outcome of a rate limit check: whether to allow, and seconds to wait if not."""

    allowed: bool
    retry_after: int = 0


class FixedWindowLimiter:
    """Allow ``limit`` calls per ``window_s`` seconds for each key."""

    def __init__(
        self,
        limit: int,
        window_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the limit and window; ``clock`` is injectable for tests."""
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self._state: dict[str, tuple[float, int]] = {}

    def check(self, key: str) -> Decision:
        """Count one call for ``key`` and return whether it is allowed."""
        now = self.clock()
        if len(self._state) > CLEANUP_THRESHOLD:
            self._cleanup(now)

        entry = self._state.get(key)
        if entry is None or now - entry[0] >= self.window_s:
            self._state[key] = (now, 1)
            return Decision(True, 0)

        start, count = entry
        if count < self.limit:
            self._state[key] = (start, count + 1)
            return Decision(True, 0)

        # Rejections do not change the count.
        retry = max(1, min(int(self.window_s), math.ceil(start + self.window_s - now)))
        return Decision(False, retry)

    def _cleanup(self, now: float) -> None:
        expired = [k for k, (s, _) in self._state.items() if now - s >= self.window_s]
        for k in expired:
            del self._state[k]
