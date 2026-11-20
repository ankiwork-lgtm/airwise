"""Browser tests for form flows: validation errors, plan render, loading states."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from playwright.sync_api import expect

from airwise.models import PlanRequest
from tests.browser.helpers import fill_valid_form

if TYPE_CHECKING:
    from tests.browser.conftest import MockApi


# a. Empty submit
def test_empty_form_submission_shows_validation_errors(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Clicking 'Generate plan' with an empty form marks invalid fields in #status."""
    page.goto(live_server)

    page.get_by_role("button", name="Generate plan").click()

    # Status live region has role="alert" and lists required fields
    status = page.locator("#status")
    expect(status).to_have_attribute("role", "alert")
    expect(status).to_contain_text("Please complete these fields:")
    li_items = status.locator("ul li")
    expect(li_items).to_have_count(9)  # City + 8 profile fields

    # Focus is moved to the first invalid field (#city)
    city_input = page.get_by_label("City")
    expect(city_input).to_be_focused()

    # City has aria-invalid="true" and aria-describedby containing 'status'
    expect(city_input).to_have_attribute("aria-invalid", "true")
    desc_by = city_input.get_attribute("aria-describedby") or ""
    assert "status" in desc_by.split()

    # No request sent to /api/plan
    assert len(mock_api.requests) == 0


# b. Fixing a field clears its aria-invalid
def test_fixing_field_clears_aria_invalid(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Entering valid input on a field clears its aria-invalid while other fields stay flagged."""
    page.goto(live_server)

    # Trigger validation errors
    page.get_by_role("button", name="Generate plan").click()
    city_input = page.get_by_label("City")
    kids_select = page.get_by_label("Children present")

    expect(city_input).to_have_attribute("aria-invalid", "true")
    expect(kids_select).to_have_attribute("aria-invalid", "true")

    # Fix city by typing a valid value
    city_input.fill("Delhi")

    # City's aria-invalid and aria-describedby are cleared
    assert city_input.get_attribute("aria-invalid") is None
    desc_by = city_input.get_attribute("aria-describedby") or ""
    assert "status" not in desc_by.split()

    # Other flagged fields remain invalid
    expect(kids_select).to_have_attribute("aria-invalid", "true")


# c. Partial profile
def test_partial_profile_flags_only_missing_field(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Submitting with only one field missing flags and focuses that specific field."""
    page.goto(live_server)

    # Fill valid form except Children present
    fill_valid_form(page, city="Delhi")
    page.get_by_label("Children present").select_option("")

    page.get_by_role("button", name="Generate plan").click()

    # Only Children present is invalid and gets focus
    kids_select = page.get_by_label("Children present")
    expect(kids_select).to_be_focused()
    expect(kids_select).to_have_attribute("aria-invalid", "true")

    # Other fields are not marked invalid
    city_input = page.get_by_label("City")
    assert city_input.get_attribute("aria-invalid") is None
    elderly_select = page.get_by_label("Elderly person present")
    assert elderly_select.get_attribute("aria-invalid") is None

    # Status alert lists only "Children present"
    status = page.locator("#status")
    expect(status).to_have_attribute("role", "alert")
    li_items = status.locator("ul li")
    expect(li_items).to_have_count(1)
    expect(li_items.first).to_have_text("Children present")

    assert len(mock_api.requests) == 0


# d. Successful plan
def test_successful_plan_submission_and_render(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Submitting valid profile POSTs payload, clears status, renders plan, AQI, impact, chat."""
    page.goto(live_server)

    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()

    # Request sent to /api/plan has expected shape
    plan_requests = [r for r in mock_api.requests if "/api/plan" in r.url]
    assert len(plan_requests) == 1
    req_json = plan_requests[0].json
    assert req_json is not None
    # Validate against Pydantic model
    validated_req = PlanRequest.model_validate(req_json)
    assert validated_req.profile.city == "Delhi"

    # Status is cleared
    status = page.locator("#status")
    expect(status).to_have_text("")

    # Result section is visible and heading is focused
    result_h = page.get_by_role("heading", name="Your air quality plan")
    expect(result_h).to_be_visible()
    expect(result_h).to_be_focused()

    # AQI card shows mock AQI value and band text
    aqi_card = page.locator(".card.aqi")
    expect(aqi_card).to_be_visible()
    expect(aqi_card.locator(".aqi-value")).to_have_text("350")
    expect(aqi_card.locator(".aqi-band")).to_contain_text("Very Poor")

    # Impact table renders with caption and th[scope="col"] headers
    table = page.locator("#result-body table")
    expect(table).to_be_visible()
    caption = table.locator("caption")
    expect(caption).to_have_text(
        "Estimated exposure and CO2 reduction for each recommended action. Figures are approximate."
    )
    headers = table.locator("th")
    expect(headers).to_have_count(5)
    for i in range(5):
        expect(headers.nth(i)).to_have_attribute("scope", "col")

    # Chat section and starters are visible
    expect(page.locator("#chat")).to_be_visible()
    expect(page.locator("#starters")).to_be_visible()
    expect(page.locator("#starters button")).to_have_count(4)


# e. Loading/disabled states & reduced motion
def test_loading_and_disabled_states_and_reduced_motion(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """While plan request is pending, button is disabled, status shows loading."""
    page.goto(live_server)

    gate = mock_api.hold("plan")
    fill_valid_form(page, city="Delhi")

    btn = page.get_by_role("button", name="Generate plan")
    status = page.locator("#status")

    # Click Generate plan to trigger in-flight request
    btn.click()

    # Status shows loading message and class
    expect(status).to_have_text("Generating your plan...")
    expect(status).to_have_class("status loading")

    # Button is disabled while request is pending
    expect(btn).to_be_disabled()

    # Second click does not trigger another request
    page.evaluate("() => document.getElementById('generate-btn').click()")
    assert len(mock_api.requests) == 1

    # Release the gate
    gate.release()

    # Button is re-enabled and results render
    expect(btn).to_be_enabled()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()

    # Reduced motion check: emulate prefers-reduced-motion: reduce
    page.emulate_media(reduced_motion="reduce")
    gate2 = mock_api.hold("plan")
    btn.click()
    expect(status).to_have_class("status loading")

    anim_name = page.evaluate(
        """() => {
            const el = document.querySelector('.loading');
            return window.getComputedStyle(el, '::before').animationName;
        }"""
    )
    assert anim_name == "none"
    gate2.release()


# f. API validation error (422)
def test_api_validation_error_422_handling(page: Any, live_server: str, mock_api: MockApi) -> None:
    """422 validation response marks control invalid, focuses it, and keeps results hidden."""
    page.goto(live_server)

    mock_api.set_plan(
        {
            "error": {
                "code": "validation_error",
                "message": "Invalid request.",
                "fields": ["profile.kids"],
            }
        },
        status=422,
    )

    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()

    # Status region shows validation error
    status = page.locator("#status")
    expect(status).to_have_attribute("role", "alert")
    expect(status).to_contain_text(
        "Some details were not accepted. Please fix the fields listed below."
    )
    expect(status.locator("ul li")).to_have_text("profile.kids")

    # Mapped control (Children present / #f-kids) receives aria-invalid and focus
    kids_select = page.get_by_label("Children present")
    expect(kids_select).to_have_attribute("aria-invalid", "true")
    expect(kids_select).to_be_focused()

    # Results stay hidden
    expect(page.locator("#result")).to_be_hidden()


# g. Server error (500) and network failure
def test_server_error_500_handling(page: Any, live_server: str, mock_api: MockApi) -> None:
    """500 error shows generic message in alert, does not move focus, keeps results hidden."""
    page.goto(live_server)

    mock_api.set_plan(
        {
            "error": {
                "code": "server_error",
                "message": "Internal server error.",
                "fields": [],
            }
        },
        status=500,
    )

    fill_valid_form(page, city="Delhi")
    btn = page.get_by_role("button", name="Generate plan")
    btn.click()

    status = page.locator("#status")
    expect(status).to_have_attribute("role", "alert")
    expect(status).to_have_text("Something went wrong on our side. Please try again later.")

    # Results stay hidden
    expect(page.locator("#result")).to_be_hidden()
    # Button re-enabled
    expect(btn).to_be_enabled()
    # Focus was not moved to result heading
    active_id = page.evaluate("() => document.activeElement ? document.activeElement.id : null")
    assert active_id != "result-h"


def test_network_failure_handling(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Network failure shows connection message, keeps results hidden, enables retry."""
    page.goto(live_server)

    gate = mock_api.hold("plan")
    fill_valid_form(page, city="Delhi")
    btn = page.get_by_role("button", name="Generate plan")
    btn.click()

    # Abort route to simulate network error
    gate.release(abort=True)

    status = page.locator("#status")
    expect(status).to_have_attribute("role", "alert")
    expect(status).to_have_text("Could not reach AirWise. Check your connection and try again.")

    expect(page.locator("#result")).to_be_hidden()
    expect(btn).to_be_enabled()


def test_rate_limited_429_handling(page: Any, live_server: str, mock_api: MockApi) -> None:
    """429 response formats message with Retry-After header or default fallback."""
    page.goto(live_server)

    # With Retry-After header
    mock_api.set_plan(
        {"error": {"code": "rate_limited", "message": "Too many requests.", "fields": []}},
        status=429,
        headers={"Retry-After": "15"},
    )
    fill_valid_form(page, city="Delhi")
    btn = page.get_by_role("button", name="Generate plan")
    btn.click()

    status = page.locator("#status")
    expect(status).to_have_attribute("role", "alert")
    expect(status).to_have_text("Too many requests. Please try again in 15 seconds.")

    # Without Retry-After header
    mock_api.set_plan(
        {"error": {"code": "rate_limited", "message": "Too many requests.", "fields": []}},
        status=429,
    )
    btn.click()
    expect(status).to_have_text("Too many requests. Please wait before trying again.")


# h. Profile saved in localStorage
def test_profile_saved_in_local_storage_on_successful_generation(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Generating a plan saves the profile to localStorage under key 'airwise.profile'."""
    page.goto(live_server)

    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()

    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()

    stored_raw = page.evaluate("() => window.localStorage.getItem('airwise.profile')")
    assert stored_raw is not None
    stored_json = json.loads(stored_raw)

    expected_keys = {
        "city",
        "kids",
        "elderly",
        "respiratory",
        "commute",
        "cooking_fuel",
        "heating",
        "has_purifier",
        "ventilation",
    }
    assert set(stored_json.keys()) == expected_keys
    assert stored_json["city"] == "Delhi"
