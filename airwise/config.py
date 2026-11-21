"""Constants and environment readers. Credentials come only from os.environ."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
AQ_SOURCE_URL = "https://open-meteo.com/en/docs/air-quality-api"  # human-readable data source
OPEN_METEO_TIMEOUT_S = 8.0
LLM_TIMEOUT_S = 20.0
REQUEST_DEADLINE_S = 28.0  # below Vercel maxDuration (30)
LLM_MIN_BUDGET_S = 2.0  # skip the LLM call if less time remains
MAX_BODY_BYTES = 65_536
PLAN_LIMIT, CHAT_LIMIT, WINDOW_S = 10, 30, 60
AQI_LIMIT = 30
ESTIMATED_PM25, ESTIMATED_PM10 = 150.0, 260.0  # typical winter values
LOOKUP_CACHE_TTL_S = 300.0  # geocode and PM lookup cache lifetime (about 5 minutes)
LOOKUP_CACHE_MAX_ENTRIES = 256  # per cache; oldest entries are evicted first

DEFAULT_LLM_MODEL = "claude-haiku-5-5"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"


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


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env_file() -> None:
    """Load KEY=VALUE lines from the project .env into os.environ, overriding existing values.

    No-op when the file is absent (e.g. on Vercel, where variables come from the platform).
    """
    path = ENV_FILE
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ[key] = value


def anthropic_api_key() -> str | None:
    """Return ANTHROPIC_API_KEY, or None when unset or empty."""
    value = os.environ.get("ANTHROPIC_API_KEY", "")
    return value if value.strip() else None


def anthropic_base_url() -> str:
    """Return ANTHROPIC_BASE_URL (ending before /messages), without a trailing slash."""
    value = os.environ.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/")
    return value or DEFAULT_ANTHROPIC_BASE_URL


def llm_model() -> str:
    """Return LLM_MODEL, defaulting to claude-haiku-5-5 when unset or empty."""
    value = os.environ.get("LLM_MODEL", "").strip()
    return value or DEFAULT_LLM_MODEL
