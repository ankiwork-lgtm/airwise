"""Smoke tests verifying real browser loading, CSP, static assets, and minimal flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.browser.conftest import MockApi


def test_page_load_and_csp(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Verifies that the page loads with expected title, h1, skip link, and zero CSP violations."""
    response = page.goto(live_server)
    assert response is not None
    assert response.status == 200
    assert page.title() == "AirWise"

    h1 = page.locator("h1")
    assert h1.is_visible()
    assert h1.inner_text() == "AirWise"

    skip_link = page.locator("a.skip-link")
    assert skip_link.count() == 1
    assert skip_link.get_attribute("href") == "#main"


def test_static_assets_content_types(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Verifies that /app.css and /app.js are served with expected content types."""
    css_res = page.request.get(f"{live_server}/app.css")
    assert css_res.status == 200
    assert "text/css" in css_res.headers.get("content-type", "")

    js_res = page.request.get(f"{live_server}/app.js")
    assert js_res.status == 200
    assert "text/javascript" in js_res.headers.get("content-type", "")


def test_security_headers_present(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Verifies that ASGI middleware security headers are present on the root document."""
    response = page.goto(live_server)
    assert response is not None
    assert response.status == 200
    headers = response.headers

    assert "content-security-policy" in headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("referrer-policy") == "no-referrer"
    assert "geolocation=(self)" in headers.get("permissions-policy", "")


def test_live_server_hermetic_environment(live_server: str) -> None:
    """Verifies that the live_server runs without a real API key or developer .env loaded."""
    import os

    from airwise.config import ENV_FILE, anthropic_api_key

    assert anthropic_api_key() is None
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert not ENV_FILE.is_file()


def test_minimal_plan_flow(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Verifies minimal form submission flow with mock_api and focus landing on result heading."""
    page.goto(live_server)

    page.fill("#city", "Delhi")
    page.select_option("#f-kids", "no")
    page.select_option("#f-elderly", "no")
    page.select_option("#f-respiratory", "no")
    page.select_option("#f-commute", "bus_metro")
    page.select_option("#f-cooking_fuel", "lpg")
    page.select_option("#f-heating", "electric")
    page.select_option("#f-has_purifier", "yes")
    page.select_option("#f-ventilation", "sometimes")

    page.click("#generate-btn")

    result_heading = page.locator("#result-h")
    result_heading.wait_for(state="visible", timeout=5000)
    assert result_heading.inner_text() == "Your air quality plan"

    # Verify focus landed on the heading (T5.3)
    active_id = page.evaluate("() => document.activeElement ? document.activeElement.id : null")
    assert active_id == "result-h"

    # Verify mock_api recorded the POST request
    plan_requests = [r for r in mock_api.requests if "/api/plan" in r.url]
    assert len(plan_requests) == 1
    req = plan_requests[0]
    assert req.method == "POST"
    assert req.json["profile"]["city"] == "Delhi"
    assert req.json["profile"]["commute"] == "bus_metro"
