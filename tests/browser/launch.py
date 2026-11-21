"""Browser launch policy for the Playwright fixtures; imports nothing from Playwright."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import pytest

REQUIRE_ENV = "AIRWISE_REQUIRE_BROWSER"
CHANNEL_ENV = "AIRWISE_BROWSER_CHANNEL"
DEFAULT_CHANNELS: list[str | None] = [None, "msedge", "chrome", "chromium"]


def browser_unavailable(reason: str, environ: Mapping[str, str] | None = None) -> None:
    """Skip the test, or fail it when AIRWISE_REQUIRE_BROWSER=1 (set in CI)."""
    env = os.environ if environ is None else environ
    if env.get(REQUIRE_ENV) == "1":
        pytest.fail(f"{reason} ({REQUIRE_ENV}=1 forbids skipping)", pytrace=False)
    pytest.skip(reason)


def launch_chromium(playwright: Any, environ: Mapping[str, str] | None = None) -> Any:
    """Launch headless Chromium: bundled first, then system channels; skip or fail if none."""
    env = os.environ if environ is None else environ
    channel = env.get(CHANNEL_ENV)
    channels: list[str | None] = [channel] if channel else DEFAULT_CHANNELS

    last_error = ""
    for ch in channels:
        try:
            if ch is None:
                return playwright.chromium.launch(headless=True)
            return playwright.chromium.launch(headless=True, channel=ch)
        except Exception as exc:
            last_error = (str(exc).strip().splitlines() or [type(exc).__name__])[0]

    browser_unavailable(
        "No Playwright browser available "
        "(run 'python -m playwright install chromium' or install Edge/Chrome). "
        f"Last error: {last_error}",
        env,
    )
    raise AssertionError("unreachable")  # pragma: no cover
