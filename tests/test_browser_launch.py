"""Tests for the browser launch policy (no browser needed: the launcher is faked)."""

from typing import Any

import pytest

from tests.browser.launch import browser_unavailable, launch_chromium


class FakeChromium:
    def __init__(self, working: set[str | None]) -> None:
        self.working = working
        self.calls: list[str | None] = []

    def launch(self, headless: bool, channel: str | None = None) -> str:
        assert headless is True
        self.calls.append(channel)
        if channel not in self.working:
            raise RuntimeError(f"cannot launch {channel}\nlong driver detail")
        return f"browser:{channel}"


class FakePlaywright:
    def __init__(self, working: set[str | None]) -> None:
        self.chromium = FakeChromium(working)


def test_unavailable_skips_by_default():
    with pytest.raises(pytest.skip.Exception):
        browser_unavailable("no browser", {})


@pytest.mark.parametrize("value", ["0", "", "true"])
def test_only_exact_one_enables_failing(value: str):
    with pytest.raises(pytest.skip.Exception):
        browser_unavailable("no browser", {"AIRWISE_REQUIRE_BROWSER": value})


def test_unavailable_fails_when_required():
    with pytest.raises(pytest.fail.Exception, match="AIRWISE_REQUIRE_BROWSER=1"):
        browser_unavailable("no browser", {"AIRWISE_REQUIRE_BROWSER": "1"})


def test_launch_prefers_bundled_chromium():
    pw: Any = FakePlaywright({None, "msedge"})
    assert launch_chromium(pw, {}) == "browser:None"
    assert pw.chromium.calls == [None]


def test_launch_falls_back_to_system_channels_in_order():
    pw: Any = FakePlaywright({"chrome"})
    assert launch_chromium(pw, {}) == "browser:chrome"
    assert pw.chromium.calls == [None, "msedge", "chrome"]


def test_launch_channel_override_tries_only_that_channel():
    pw: Any = FakePlaywright({None, "chrome"})
    assert launch_chromium(pw, {"AIRWISE_BROWSER_CHANNEL": "chrome"}) == "browser:chrome"
    assert pw.chromium.calls == ["chrome"]


def test_launch_skips_when_nothing_launches():
    pw: Any = FakePlaywright(set())
    with pytest.raises(pytest.skip.Exception, match="cannot launch chromium"):
        launch_chromium(pw, {})
    assert pw.chromium.calls == [None, "msedge", "chrome", "chromium"]


def test_launch_fails_instead_of_skipping_when_required():
    pw: Any = FakePlaywright(set())
    env = {"AIRWISE_REQUIRE_BROWSER": "1", "AIRWISE_BROWSER_CHANNEL": "nonexistent"}
    with pytest.raises(pytest.fail.Exception, match="cannot launch nonexistent"):
        launch_chromium(pw, env)
    assert pw.chromium.calls == ["nonexistent"]
