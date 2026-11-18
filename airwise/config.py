"""Constants and environment readers. Credentials come only from os.environ."""
from __future__ import annotations

import os
import time
from collections.abc import Callable

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_TIMEOUT_S = 8.0
LLM_TIMEOUT_S = 20.0
REQUEST_DEADLINE_S = 28.0  # below Vercel maxDuration (30)
LLM_MIN_BUDGET_S = 2.0  # skip the LLM call if less time remains
MAX_BODY_BYTES = 65_536
PLAN_LIMIT, CHAT_LIMIT, WINDOW_S = 10, 30, 60
ESTIMATED_PM25, ESTIMATED_PM10 = 150.0, 260.0  # typical winter values

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class Deadline:
    """Per-request time budget. Pure apart from the injectable monotonic clock."""

    def __init__(
        self,
        total_s: float = REQUEST_DEADLINE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._end = clock() + total_s

    def remaining(self) -> float:
        """Seconds left, never below 0."""
        return max(0.0, self._end - self._clock())

    def llm_timeout(self) -> float:
        """Planned LLM timeout: min(LLM_TIMEOUT_S, remaining - 1), never below 0."""
        return max(0.0, min(LLM_TIMEOUT_S, self.remaining() - 1.0))

    def should_skip_llm(self) -> bool:
        """True when less than LLM_MIN_BUDGET_S remains."""
        return self.remaining() < LLM_MIN_BUDGET_S


def openai_api_key() -> str | None:
    """Return OPENAI_API_KEY, or None when unset or empty."""
    value = os.environ.get("OPENAI_API_KEY", "")
    return value if value.strip() else None


def openai_model() -> str:
    """Return OPENAI_MODEL, defaulting to gpt-4o-mini when unset or empty."""
    value = os.environ.get("OPENAI_MODEL", "").strip()
    return value or DEFAULT_OPENAI_MODEL
