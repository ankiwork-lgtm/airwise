"""Browser layout tests verifying sticky banner and responsive viewport behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from playwright.sync_api import expect

from tests.browser.helpers import (
    check_focused_element,
    fill_valid_form,
)

if TYPE_CHECKING:
    from tests.browser.conftest import MockApi


def test_disclaimer_is_sticky_on_wide_and_tall_viewport(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """At 1280x800, disclaimer stays pinned at top:0 when scrolled, reserving scroll padding."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(live_server)

    # Render plan so page is tall enough to scroll
    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()

    # Initial scroll-padding-top
    scroll_padding = page.evaluate(
        "() => window.getComputedStyle(document.documentElement).scrollPaddingTop"
    )
    assert scroll_padding == "56px"

    # Scroll to the bottom
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")

    layout_info = page.evaluate("""() => {
        const el = document.querySelector('.disclaimer');
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const topEl = document.elementFromPoint(cx, cy);
        return {
            scrollY: window.scrollY,
            top: rect.top,
            bottom: rect.bottom,
            height: rect.height,
            position: style.position,
            isTopElement: !!topEl && (topEl === el || el.contains(topEl)),
            inViewport: rect.top >= 0 && rect.bottom <= window.innerHeight
        };
    }""")

    assert layout_info["scrollY"] > 500, "Page should be scrolled down"
    assert layout_info["position"] == "sticky"
    assert abs(layout_info["top"]) <= 1.0, f"Expected top ~0, got {layout_info['top']}"
    assert layout_info["inViewport"], "Disclaimer should be within viewport"
    assert layout_info["isTopElement"], "Disclaimer center should be top element at point"

    # Focus a control near the bottom (chat input) and assert it is not obscured by sticky banner
    page.locator("#chat-input").focus()
    focus_info = check_focused_element(page)
    assert focus_info["id"] == "chat-input"
    assert focus_info["inViewport"], "Focused chat input should be in viewport"
    assert focus_info["notCovered"], "Focused chat input should not be covered by sticky banner"


def test_disclaimer_is_static_on_narrow_viewport_320x256(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """At 320x256 (narrow and short), disclaimer is static and scrolls away."""
    page.set_viewport_size({"width": 320, "height": 256})
    page.goto(live_server)

    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()

    style_info = page.evaluate("""() => {
        const el = document.querySelector('.disclaimer');
        return {
            position: window.getComputedStyle(el).position,
            scrollPaddingTop: window.getComputedStyle(document.documentElement).scrollPaddingTop
        };
    }""")
    assert style_info["position"] == "static"
    assert style_info["scrollPaddingTop"] == "0px"

    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    rect_bottom = page.evaluate(
        "() => document.querySelector('.disclaimer').getBoundingClientRect().bottom"
    )
    assert rect_bottom <= 0, f"Expected disclaimer to scroll away (bottom <= 0), got {rect_bottom}"


def test_disclaimer_is_static_on_narrow_viewport_640x800(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """At 640x800 (<= 40em width), disclaimer is static and scrolls away."""
    page.set_viewport_size({"width": 640, "height": 800})
    page.goto(live_server)

    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()

    style_info = page.evaluate("""() => {
        const el = document.querySelector('.disclaimer');
        return {
            position: window.getComputedStyle(el).position,
            scrollPaddingTop: window.getComputedStyle(document.documentElement).scrollPaddingTop
        };
    }""")
    assert style_info["position"] == "static"
    assert style_info["scrollPaddingTop"] == "0px"

    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    rect_bottom = page.evaluate(
        "() => document.querySelector('.disclaimer').getBoundingClientRect().bottom"
    )
    assert rect_bottom <= 0, f"Expected disclaimer to scroll away (bottom <= 0), got {rect_bottom}"


def test_disclaimer_is_static_on_short_viewport_1280x400(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """At 1280x400 (<= 32em height = 512px), disclaimer is static and scrolls away."""
    page.set_viewport_size({"width": 1280, "height": 400})
    page.goto(live_server)

    fill_valid_form(page, city="Delhi")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()

    style_info = page.evaluate("""() => {
        const el = document.querySelector('.disclaimer');
        return {
            position: window.getComputedStyle(el).position,
            scrollPaddingTop: window.getComputedStyle(document.documentElement).scrollPaddingTop
        };
    }""")
    assert style_info["position"] == "static"
    assert style_info["scrollPaddingTop"] == "0px"

    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    rect_bottom = page.evaluate(
        "() => document.querySelector('.disclaimer').getBoundingClientRect().bottom"
    )
    assert rect_bottom <= 0, f"Expected disclaimer to scroll away (bottom <= 0), got {rect_bottom}"
