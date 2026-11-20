"""Browser accessibility tests using vendored axe-core.

Verifies WCAG 2.0 / 2.1 A and AA rules across all real page states.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from playwright.sync_api import expect

from tests.browser.helpers import (
    AXE_VENDOR_PATH,
    EXPECTED_AXE_SHA256,
    GEOLOCATION_STUB,
    assert_no_axe_violations,
    fill_valid_form,
    geo_fail,
    run_axe,
)

if TYPE_CHECKING:
    from tests.browser.conftest import MockApi


def test_vendored_axe_integrity() -> None:
    """Recomputes SHA-256 of vendored axe.min.js and compares to the recorded hash."""
    assert AXE_VENDOR_PATH.exists(), f"Missing vendored axe at {AXE_VENDOR_PATH}"
    content = AXE_VENDOR_PATH.read_bytes()
    assert len(content) > 0, "Vendored axe.min.js is empty"
    actual_hash = hashlib.sha256(content).hexdigest()
    assert actual_hash == EXPECTED_AXE_SHA256, (
        f"Axe integrity mismatch: expected {EXPECTED_AXE_SHA256}, got {actual_hash}"
    )


# (a) Initial load
def test_axe_scan_initial_load(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Axe scan on initial clean page load."""
    page.goto(live_server)
    expect(page.get_by_role("heading", name="AirWise")).to_be_visible()
    results = run_axe(page)
    assert_no_axe_violations(results)


# (b) Validation failure
def test_axe_scan_validation_failure(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Axe scan after empty submit triggers validation errors and aria-invalid."""
    page.goto(live_server)
    page.get_by_role("button", name="Generate plan").click()
    expect(page.locator("#status")).to_contain_text("Please complete these fields:")
    expect(page.get_by_label("City")).to_have_attribute("aria-invalid", "true")

    results = run_axe(page)
    assert_no_axe_violations(results)


# (c) Loading state
def test_axe_scan_loading_state(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Axe scan while plan generation request is held in flight."""
    hold = mock_api.hold("plan")
    page.goto(live_server)
    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()

    expect(page.locator("#status")).to_contain_text("Generating your plan...")
    expect(page.get_by_role("button", name="Generate plan")).to_be_disabled()

    results = run_axe(page)
    assert_no_axe_violations(results)
    hold.release()


# (d) Successful plan
def test_axe_scan_successful_plan(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Axe scan after a plan and air reading are rendered."""
    page.goto(live_server)
    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()

    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()
    expect(page.get_by_role("heading", name="Air quality in Delhi")).to_be_visible()
    expect(page.get_by_role("heading", name="Impact table")).to_be_visible()

    results = run_axe(page)
    assert_no_axe_violations(results)


# (e) Chat states (user, assistant, failed bubbles)
def test_axe_scan_chat_states(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Axe scan with user, assistant and failed chat bubbles present."""
    page.goto(live_server)
    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Ask a follow-up")).to_be_visible()

    # Successful turn
    mock_api.set_chat({"reply": "Keep windows closed during early morning.", "failed": False})
    chat_input = page.get_by_label("Your question")
    chat_input.fill("What should I do first?")
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".bubble.assistant")).to_contain_text("Keep windows closed")

    # Failed turn
    mock_api.set_chat({"reply": "API failure", "failed": True}, status=500)
    chat_input.fill("Another question")
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".bubble.failed")).to_be_visible()

    results = run_axe(page)
    assert_no_axe_violations(results)


# (f) Error state from API (500 alert)
def test_axe_scan_api_error_state(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Axe scan after server 500 error response is shown in #status."""
    mock_api.set_plan({"error": {"code": "server_error"}}, status=500)
    page.goto(live_server)
    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()

    expect(page.locator("#status")).to_contain_text("Something went wrong on our side")
    expect(page.locator("#status")).to_have_attribute("role", "alert")

    results = run_axe(page)
    assert_no_axe_violations(results)


# (g) Geolocation error state
def test_axe_scan_geolocation_error_state(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Axe scan after geolocation permission denial."""
    page.add_init_script(GEOLOCATION_STUB)
    page.goto(live_server)
    page.get_by_role("button", name="Use my location").click()
    geo_fail(page, code=1)  # PERMISSION_DENIED

    expect(page.locator("#geo-status")).to_contain_text("We could not get your location")
    expect(page.locator("#geo-status")).to_have_attribute("role", "alert")

    results = run_axe(page)
    assert_no_axe_violations(results)


# (h) Reduced motion and narrow 320x256 reflow viewport
def test_axe_scan_reduced_motion_and_reflow_viewport(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Axe scan under reduced motion emulation and narrow 320x256 viewport."""
    page.set_viewport_size({"width": 320, "height": 256})
    page.emulate_media(reduced_motion="reduce")
    page.goto(live_server)
    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()

    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()

    results = run_axe(page)
    assert_no_axe_violations(results)


# (i) Focus-visible states
def test_axe_scan_focus_visible_states(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Axe scan with focus on skip link and on text input."""
    page.goto(live_server)

    # Focus skip link
    page.locator(".skip-link").focus()
    results_skip = run_axe(page)
    assert_no_axe_violations(results_skip)

    # Focus city input
    page.get_by_label("City").focus()
    results_city = run_axe(page)
    assert_no_axe_violations(results_city)


# Needs-review / incomplete reporting
def test_axe_incomplete_items_are_reported_and_understood(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Inspects axe 'incomplete' (needs-review) items and confirms expected items."""
    page.goto(live_server)
    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()

    results = run_axe(page)
    incomplete = results.get("incomplete", [])
    # Incomplete items in axe-core are rules requiring human review (e.g. color contrast).
    for item in incomplete:
        assert item.get("id") in {
            "color-contrast",
        }, f"Unexpected incomplete rule: {item.get('id')}"
