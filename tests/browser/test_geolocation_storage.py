"""Browser tests for geolocation ('Use my location') and the localStorage saved profile."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from tests.browser.helpers import (
    GEOLOCATION_STUB,
    NO_GEOLOCATION,
    fill_profile_selects,
    fill_valid_form,
    geo_fail,
    geo_succeed,
    save_real_profile,
    seed_storage,
    stored_profile,
)

if TYPE_CHECKING:
    from tests.browser.conftest import MockApi

NO_LOCATION = "We could not get your location. Please enter a city name instead."
PERMISSION_DENIED = 1
POSITION_UNAVAILABLE = 2
TIMEOUT_CODE = 3
EXPLICIT_TIMEOUT_MS = 5000


def _aqi_requests(mock_api: MockApi) -> list[Any]:
    return [r for r in mock_api.requests if "/api/aqi" in r.url]


def _plan_requests(mock_api: MockApi) -> list[Any]:
    return [r for r in mock_api.requests if "/api/plan" in r.url]


def _active_id(page: Any) -> str | None:
    return page.evaluate("() => document.activeElement ? document.activeElement.id : null")


def _assert_empty_form(page: Any) -> None:
    expect(page.locator("#city")).to_have_value("", timeout=EXPLICIT_TIMEOUT_MS)
    for select in page.locator("#fields select").all():
        expect(select).to_have_value("", timeout=EXPLICIT_TIMEOUT_MS)


# ---------------------------------------------------------------------------
# Geolocation
# ---------------------------------------------------------------------------


# a. Success
def test_geolocation_success_renders_reading_without_plan_then_generates(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """A stubbed position loads the AQI card (no plan), then Generate sends the coordinates."""
    page.add_init_script(GEOLOCATION_STUB)
    page.goto(live_server)

    geo_status = page.locator("#geo-status")
    btn = page.get_by_role("button", name="Use my location")
    gate = mock_api.hold("aqi")

    btn.click()
    expect(geo_status).to_have_text("Finding your location...", timeout=EXPLICIT_TIMEOUT_MS)
    expect(geo_status).to_have_class("status loading")
    expect(btn).to_be_disabled()
    assert page.evaluate("() => window.__geo.last().options.timeout") == 10000
    assert _aqi_requests(mock_api) == []

    geo_succeed(page, 28.6139, 77.2090)
    expect(geo_status).to_have_text(
        "Looking up air quality for your location...", timeout=EXPLICIT_TIMEOUT_MS
    )
    expect(geo_status).to_have_class("status loading")

    # Coordinates are sent unrounded, exactly as the browser reported them.
    expect(page.locator("#city")).to_have_value("My location")
    aqi = _aqi_requests(mock_api)
    assert len(aqi) == 1
    assert aqi[0].method == "GET"
    parts = urlsplit(aqi[0].url)
    assert parts.path == "/api/aqi"
    assert parse_qs(parts.query) == {"lat": ["28.6139"], "lon": ["77.209"]}

    gate.release()
    expect(geo_status).to_have_text(
        "Using your location. Complete the profile and choose Generate plan.",
        timeout=EXPLICIT_TIMEOUT_MS,
    )
    expect(geo_status).to_have_attribute("role", "status")
    expect(btn).to_be_enabled()

    # Reading-only render: AQI card visible, plan heading hidden and not focused (T5.3).
    expect(page.locator("#result")).to_be_visible()
    expect(page.locator(".card.aqi .aqi-value")).to_have_text("350")
    heading = page.locator("#result-h")
    expect(heading).to_be_hidden()
    expect(heading).not_to_be_focused()
    expect(page.locator("#chat")).to_be_hidden()
    assert _plan_requests(mock_api) == []

    # Generate after filling the profile posts the coordinates with the fallback city.
    fill_profile_selects(page)
    page.get_by_role("button", name="Generate plan").click()
    expect(heading).to_be_visible(timeout=EXPLICIT_TIMEOUT_MS)
    expect(heading).to_be_focused()
    plan = _plan_requests(mock_api)
    assert len(plan) == 1
    assert plan[0].json["latitude"] == pytest.approx(28.6139)
    assert plan[0].json["longitude"] == pytest.approx(77.2090)
    assert plan[0].json["profile"]["city"] == "My location"


# b. Permission denied (and other error codes)
@pytest.mark.parametrize("code", [PERMISSION_DENIED, POSITION_UNAVAILABLE, TIMEOUT_CODE])
def test_geolocation_error_callback_shows_message(
    page: Any, live_server: str, mock_api: MockApi, code: int
) -> None:
    """Any geolocation error shows the city fallback message without moving focus."""
    page.add_init_script(GEOLOCATION_STUB)
    page.goto(live_server)

    geo_status = page.locator("#geo-status")
    btn = page.get_by_role("button", name="Use my location")
    btn.click()
    expect(geo_status).to_have_text("Finding your location...", timeout=EXPLICIT_TIMEOUT_MS)

    geo_fail(page, code)
    expect(geo_status).to_have_text(NO_LOCATION, timeout=EXPLICIT_TIMEOUT_MS)
    expect(geo_status).to_have_attribute("role", "alert")
    expect(geo_status).to_have_class("status error")
    expect(btn).to_be_enabled()
    assert _aqi_requests(mock_api) == []
    assert _active_id(page) not in {"city", "result-h"}
    expect(page.locator("#result")).to_be_hidden()

    # The city input stays usable and a city-based plan works.
    city = page.get_by_label("City")
    expect(city).to_be_enabled()
    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(
        timeout=EXPLICIT_TIMEOUT_MS
    )
    plan = _plan_requests(mock_api)
    assert len(plan) == 1
    assert "latitude" not in plan[0].json
    assert plan[0].json["profile"]["city"] == "Delhi"


def test_geolocation_native_permission_denied_via_browser_context(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Without a grant, headless Chromium denies the real API: the same message appears."""
    page.goto(live_server)
    btn = page.get_by_role("button", name="Use my location")
    btn.click()
    geo_status = page.locator("#geo-status")
    expect(geo_status).to_have_text(NO_LOCATION, timeout=EXPLICIT_TIMEOUT_MS)
    expect(geo_status).to_have_attribute("role", "alert")
    expect(btn).to_be_enabled()
    assert _aqi_requests(mock_api) == []


# c. Timeout
def test_geolocation_timeout_shows_message_and_ignores_late_success(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """The app's own 10 s timer fires (fake clock); a late position cannot override it."""
    page.clock.install()
    page.add_init_script(GEOLOCATION_STUB)
    page.goto(live_server)

    geo_status = page.locator("#geo-status")
    btn = page.get_by_role("button", name="Use my location")
    btn.click()
    expect(geo_status).to_have_text("Finding your location...", timeout=EXPLICIT_TIMEOUT_MS)

    page.clock.fast_forward(9_000)
    expect(geo_status).to_have_text("Finding your location...")
    expect(btn).to_be_disabled()

    page.clock.fast_forward(1_500)
    expect(geo_status).to_have_text(NO_LOCATION, timeout=EXPLICIT_TIMEOUT_MS)
    expect(geo_status).to_have_attribute("role", "alert")
    expect(btn).to_be_enabled()
    assert _active_id(page) not in {"city", "result-h"}

    # A late success and a late error callback are both ignored (settled guard).
    geo_succeed(page, 28.6139, 77.2090)
    geo_fail(page, PERMISSION_DENIED)
    page.clock.fast_forward(1_000)
    expect(geo_status).to_have_text(NO_LOCATION)
    expect(geo_status).to_have_attribute("role", "alert")
    expect(page.locator("#city")).to_have_value("")
    assert _aqi_requests(mock_api) == []
    expect(page.locator("#result")).to_be_hidden()


def test_geolocation_timer_does_not_cut_off_a_lookup_in_flight(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Once a position arrives, the timeout must not report an error during the AQI lookup."""
    page.clock.install()
    page.add_init_script(GEOLOCATION_STUB)
    page.goto(live_server)

    geo_status = page.locator("#geo-status")
    gate = mock_api.hold("aqi")
    page.get_by_role("button", name="Use my location").click()
    geo_succeed(page, 28.6139, 77.2090)
    expect(geo_status).to_have_text(
        "Looking up air quality for your location...", timeout=EXPLICIT_TIMEOUT_MS
    )

    page.clock.fast_forward(10_500)
    expect(geo_status).to_have_text("Looking up air quality for your location...")
    expect(geo_status).not_to_have_attribute("role", "alert")

    gate.release()
    expect(geo_status).to_have_text(
        "Using your location. Complete the profile and choose Generate plan.",
        timeout=EXPLICIT_TIMEOUT_MS,
    )
    expect(page.get_by_role("button", name="Use my location")).to_be_enabled()


# d. API missing
def test_geolocation_api_missing_shows_message_immediately(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """With navigator.geolocation undefined the message appears at once and nothing is sent."""
    page.add_init_script(NO_GEOLOCATION)
    page.goto(live_server)
    assert page.evaluate("() => navigator.geolocation") is None

    btn = page.get_by_role("button", name="Use my location")
    btn.click()
    geo_status = page.locator("#geo-status")
    expect(geo_status).to_have_text(NO_LOCATION, timeout=EXPLICIT_TIMEOUT_MS)
    expect(geo_status).to_have_attribute("role", "alert")
    expect(btn).to_be_enabled()
    expect(page.get_by_label("City")).to_be_enabled()
    assert mock_api.requests == []


# e. /api/aqi failures after a successful position
@pytest.mark.parametrize(
    ("status", "body", "message", "items"),
    [
        (
            502,
            {"error": {"code": "lookup_unavailable", "message": "boom", "fields": []}},
            "The location lookup service is not responding. Please try again in a moment.",
            [],
        ),
        (
            500,
            {"error": {"code": "server_error", "message": "boom", "fields": []}},
            "Something went wrong on our side. Please try again later.",
            [],
        ),
        (
            502,
            {"detail": "Traceback (most recent call last): File app.py line 1"},
            "Something went wrong on our side. Please try again later.",
            [],
        ),
        (
            422,
            {"error": {"code": "validation_error", "message": "x", "fields": ["lat", "lon"]}},
            "Some details were not accepted. Please fix the fields listed below.",
            ["lat", "lon"],
        ),
    ],
    ids=["502-envelope", "500-envelope", "502-no-envelope", "422-envelope"],
)
def test_aqi_failure_after_position_shows_generic_alert(
    page: Any,
    live_server: str,
    mock_api: MockApi,
    status: int,
    body: dict[str, Any],
    message: str,
    items: list[str],
) -> None:
    """A failed lookup shows a generic alert, re-enables the button and keeps city entry usable."""
    page.add_init_script(GEOLOCATION_STUB)
    page.goto(live_server)
    mock_api.set_aqi(body, status=status)

    btn = page.get_by_role("button", name="Use my location")
    btn.click()
    geo_succeed(page, 28.6139, 77.2090)

    geo_status = page.locator("#geo-status")
    expect(geo_status).to_contain_text(message, timeout=EXPLICIT_TIMEOUT_MS)
    expect(geo_status).to_have_attribute("role", "alert")
    expect(geo_status).not_to_contain_text("Traceback")
    expect(geo_status.locator("li")).to_have_text(items)
    expect(btn).to_be_enabled()
    expect(page.locator("#result")).to_be_hidden()
    assert len(_aqi_requests(mock_api)) == 1
    assert _active_id(page) not in {"city", "result-h"}

    # Coordinates were not kept: a city-based plan is sent without them.
    page.get_by_label("City").fill("Pune")
    fill_profile_selects(page)
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(
        timeout=EXPLICIT_TIMEOUT_MS
    )
    plan = _plan_requests(mock_api)
    assert len(plan) == 1
    assert "latitude" not in plan[0].json
    assert plan[0].json["profile"]["city"] == "Pune"


# f. Rate limit
@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({"Retry-After": "7"}, "Too many requests. Please try again in 7 seconds."),
        ({}, "Too many requests. Please wait before trying again."),
    ],
    ids=["with-retry-after", "without-retry-after"],
)
def test_aqi_rate_limit_shows_message(
    page: Any, live_server: str, mock_api: MockApi, headers: dict[str, str], message: str
) -> None:
    """A 429 from /api/aqi shows the rate-limit message and re-enables the button."""
    page.add_init_script(GEOLOCATION_STUB)
    page.goto(live_server)
    mock_api.set_aqi(
        {"error": {"code": "rate_limited", "message": "Too many.", "fields": []}},
        status=429,
        headers=headers,
    )

    btn = page.get_by_role("button", name="Use my location")
    btn.click()
    geo_succeed(page, 28.6139, 77.2090)

    geo_status = page.locator("#geo-status")
    expect(geo_status).to_have_text(message, timeout=EXPLICIT_TIMEOUT_MS)
    expect(geo_status).to_have_attribute("role", "alert")
    expect(btn).to_be_enabled()
    expect(page.locator("#result")).to_be_hidden()


# ---------------------------------------------------------------------------
# localStorage
# ---------------------------------------------------------------------------


# g. Prefill
def test_saved_profile_prefills_form_after_reload(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """A saved profile fills the city and every select on load, and sends nothing by itself."""
    saved = save_real_profile(page, live_server, city="Mumbai")
    sent_before = len(mock_api.requests)

    page.reload()
    expect(page.locator("#city")).to_have_value("Mumbai", timeout=EXPLICIT_TIMEOUT_MS)
    for name, value in saved["selects"].items():
        expect(page.locator(f"#{name}")).to_have_value(value, timeout=EXPLICIT_TIMEOUT_MS)
    expect(page.locator("#status")).to_have_text("")
    expect(page.locator("#result")).to_be_hidden()
    assert len(mock_api.requests) == sent_before

    # The prefilled form is submittable without further input.
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(
        timeout=EXPLICIT_TIMEOUT_MS
    )
    assert len(mock_api.requests) == sent_before + 1


# h. Clear
def test_clear_saved_profile_resets_everything(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Clear removes the key, empties the form, clears geo and invalid marks, and sticks."""
    page.add_init_script(GEOLOCATION_STUB)
    save_real_profile(page, live_server, city="Mumbai")
    page.reload()

    # Put a geolocation error and an invalid mark on screen first.
    page.get_by_role("button", name="Use my location").click()
    geo_fail(page, PERMISSION_DENIED)
    geo_status = page.locator("#geo-status")
    expect(geo_status).to_have_text(NO_LOCATION, timeout=EXPLICIT_TIMEOUT_MS)
    city = page.get_by_label("City")
    city.fill("")
    page.get_by_role("button", name="Generate plan").click()
    expect(city).to_have_attribute("aria-invalid", "true", timeout=EXPLICIT_TIMEOUT_MS)

    page.get_by_role("button", name="Clear saved profile").click()

    status = page.locator("#status")
    expect(status).to_have_text("Saved profile cleared.", timeout=EXPLICIT_TIMEOUT_MS)
    expect(status).to_have_attribute("role", "status")
    expect(geo_status).to_have_text("")
    expect(geo_status).to_have_attribute("role", "status")
    _assert_empty_form(page)
    assert page.locator("[aria-invalid]").count() == 0
    assert page.locator("[aria-describedby~='status']").count() == 0
    assert stored_profile(page) is None

    page.reload()
    _assert_empty_form(page)
    assert stored_profile(page) is None


# i. Corrupted data
def _corrupt_cases() -> dict[str, Any]:
    def mutate(**changes: Any) -> Any:
        return lambda valid: {**valid, **changes}

    return {
        "invalid-json": lambda valid: "{not json",
        "empty-string": lambda valid: "",
        "json-null": lambda valid: "null",
        "json-string": lambda valid: json.dumps("airwise"),
        "json-number": lambda valid: "42",
        "json-array": lambda valid: json.dumps([valid]),
        "empty-object": lambda valid: "{}",
        "unknown-keys": lambda valid: json.dumps({f"{k}_x": v for k, v in valid.items()}),
        "extra-key": mutate(extra=1),
        "missing-key": lambda valid: {k: v for k, v in valid.items() if k != "kids"},
        "city-number": mutate(city=5),
        "city-null": mutate(city=None),
        "city-blank": mutate(city="   "),
        "city-oversized": mutate(city="x" * 101),
        "bool-as-string": mutate(kids="yes"),
        "bool-as-null": mutate(elderly=None),
        "enum-as-bool": mutate(commute=True),
        "enum-not-allowed": mutate(commute="teleport"),
        "enum-wrong-case": mutate(cooking_fuel="LPG"),
        "prototype-key": lambda valid: '{"__proto__": {"kids": true}, "city": "Delhi"}',
    }


@pytest.mark.parametrize("case", list(_corrupt_cases()))
def test_corrupted_saved_profile_gives_empty_form_and_recovers(
    page: Any, live_server: str, mock_api: MockApi, case: str
) -> None:
    """Bad saved data never throws: the form is empty, the entry is dropped, Generate recovers."""
    valid = save_real_profile(page, live_server, city="Mumbai")["profile"]
    corrupted = _corrupt_cases()[case](valid)
    seed_storage(page, corrupted if isinstance(corrupted, str) else json.dumps(corrupted))
    sent_before = len(mock_api.requests)

    page.reload()
    _assert_empty_form(page)
    expect(page.locator("#status")).to_have_text("")
    expect(page.locator("#result")).to_be_hidden()
    assert stored_profile(page) is None
    assert len(mock_api.requests) == sent_before

    fill_valid_form(page, city="Chennai")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(
        timeout=EXPLICIT_TIMEOUT_MS
    )
    resaved = stored_profile(page)
    assert resaved is not None
    assert resaved["city"] == "Chennai"
    assert set(resaved) == set(valid)


# j. Storage unavailable
STORAGE_GETTER_THROWS = """
Object.defineProperty(window, 'localStorage', {
    configurable: true,
    get() { throw new DOMException('The operation is insecure.', 'SecurityError'); },
});
"""

STORAGE_SET_ITEM_QUOTA = """
Storage.prototype.setItem = function () {
    throw new DOMException('The quota has been exceeded.', 'QuotaExceededError');
};
"""


@pytest.mark.parametrize(
    "script", [STORAGE_GETTER_THROWS, STORAGE_SET_ITEM_QUOTA], ids=["access-denied", "quota"]
)
def test_storage_unavailable_does_not_break_the_app(
    page: Any, live_server: str, mock_api: MockApi, script: str
) -> None:
    """The page loads and a plan renders when storage access or writes throw."""
    page.add_init_script(script)
    page.goto(live_server)
    _assert_empty_form(page)

    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(
        timeout=EXPLICIT_TIMEOUT_MS
    )
    expect(page.locator("#status")).to_have_text("")
    expect(page.locator(".card.aqi .aqi-value")).to_have_text("350")

    # Clear must not throw either.
    page.get_by_role("button", name="Clear saved profile").click()
    expect(page.locator("#status")).to_have_text(
        "Saved profile cleared.", timeout=EXPLICIT_TIMEOUT_MS
    )
    _assert_empty_form(page)


# k. Security
def test_saved_profile_holds_only_profile_fields(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """The saved JSON has exactly the profile keys, a trimmed city, and no plan or reply data."""
    page.goto(live_server)
    select_ids = [s.get_attribute("name") for s in page.locator("#fields select").all()]
    fill_valid_form(page, city="  Pune  ")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(
        timeout=EXPLICIT_TIMEOUT_MS
    )

    raw = page.evaluate("() => window.localStorage.getItem('airwise.profile')")
    saved = json.loads(raw)
    assert set(saved) == {"city", *select_ids}
    assert saved["city"] == "Pune"
    for forbidden in ("plan", "reading", "history", "reply", "aqi", "Keep windows closed"):
        assert forbidden not in raw
    assert page.evaluate("() => Object.keys(window.localStorage)") == ["airwise.profile"]
    assert page.evaluate("() => Object.keys(window.sessionStorage)") == []


def test_saved_city_with_markup_is_shown_as_text_only(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """A stored city such as '<img src=x onerror=1>' is an input value, never an element."""
    markup = "<img src=x onerror=1>"
    valid = save_real_profile(page, live_server, city="Mumbai")["profile"]
    seed_storage(page, json.dumps({**valid, "city": markup}))

    page.reload()
    expect(page.locator("#city")).to_have_value(markup, timeout=EXPLICIT_TIMEOUT_MS)
    assert page.locator("img").count() == 0
    assert page.locator("[onerror]").count() == 0

    # It is also rendered as text after a plan, and saved back unchanged.
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(
        timeout=EXPLICIT_TIMEOUT_MS
    )
    assert page.locator("#result-body img, #result-body [onerror]").count() == 0
    assert _plan_requests(mock_api)[-1].json["profile"]["city"] == markup
    assert (stored_profile(page) or {})["city"] == markup
