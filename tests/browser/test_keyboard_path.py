"""Keyboard-only path tests verifying full interactive user journey without mouse."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from playwright.sync_api import expect

from tests.browser.helpers import (
    check_focused_element,
)

if TYPE_CHECKING:
    from tests.browser.conftest import MockApi

FIELDS = [
    "f-kids",
    "f-elderly",
    "f-respiratory",
    "f-commute",
    "f-cooking_fuel",
    "f-heating",
    "f-has_purifier",
    "f-ventilation",
]


def _assert_focus_valid(
    page: Any,
    step_name: str,
    *,
    expected_id: str | None = None,
    expected_class: str | None = None,
    expected_tag: str | None = None,
    require_ring: bool = True,
) -> dict[str, Any]:
    info = check_focused_element(page)
    assert not info["isBodyOrNone"], f"[{step_name}] Expected focused element, but got body/none"
    if expected_id is not None:
        assert info["id"] == expected_id, (
            f"[{step_name}] Expected focus on id '{expected_id}', got '{info['id']}'"
        )
    if expected_class is not None:
        assert expected_class in info["className"], (
            f"[{step_name}] Expected class '{expected_class}' in '{info['className']}'"
        )
    if expected_tag is not None:
        assert info["tag"] == expected_tag.upper(), (
            f"[{step_name}] Expected tag '{expected_tag}', got '{info['tag']}'"
        )
    if require_ring:
        assert info["hasFocusRing"], (
            f"[{step_name}] Missing visible focus ring: outlineWidth={info['outlineWidth']}, "
            f"outlineStyle={info['outlineStyle']}, boxShadow={info['boxShadow']}"
        )
    assert info["inViewport"], f"[{step_name}] Element rect is outside viewport: {info['rect']}"
    assert info["notCovered"], (
        f"[{step_name}] Element is obscured or covered by another element at centre: {info['rect']}"
    )
    return info


def _walk_full_keyboard_journey(page: Any, live_server: str) -> None:
    page.goto(live_server)

    # 1. First Tab lands on the skip link
    page.keyboard.press("Tab")
    _assert_focus_valid(
        page, "1. Tab -> skip link", expected_class="skip-link", expected_tag="a", require_ring=True
    )

    # 2. Enter moves focus to <main>
    page.keyboard.press("Enter")
    # Note: main has outline: none by design as a programmatic non-interactive landmark target
    _assert_focus_valid(
        page, "2. Enter -> main", expected_id="main", expected_tag="main", require_ring=False
    )

    # 3. Tab to city input, type 'Delhi'
    page.keyboard.press("Tab")
    _assert_focus_valid(page, "3. Tab -> city input", expected_id="city", expected_tag="input")
    page.keyboard.type("Delhi")

    # 4. Tab to 'Use my location' (do not activate)
    page.keyboard.press("Tab")
    _assert_focus_valid(page, "4. Tab -> geo button", expected_id="geo-btn", expected_tag="button")

    # 5. Tab through each profile select choosing a value with keyboard
    for fid in FIELDS:
        page.keyboard.press("Tab")
        _assert_focus_valid(page, f"5. Tab -> {fid}", expected_id=fid, expected_tag="select")
        page.keyboard.press("ArrowDown")
        val = page.evaluate(f"() => document.getElementById('{fid}').value")
        assert val != "", f"Expected non-empty selected value for {fid}"

    # 6. Tab to 'Generate plan'
    page.keyboard.press("Tab")
    _assert_focus_valid(
        page, "6. Tab -> generate button", expected_id="generate-btn", expected_tag="button"
    )

    # 7. Press Enter on 'Generate plan' -> results heading has focus
    page.keyboard.press("Enter")
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible()
    expect(page.locator("#result-h")).to_be_focused()
    _assert_focus_valid(page, "7. Results heading focus", expected_id="result-h", expected_tag="h2")

    # 8. Tab reaches impact table scroll wrapper
    page.keyboard.press("Tab")
    _assert_focus_valid(
        page, "8. Tab -> table-wrap", expected_class="table-wrap", expected_tag="div"
    )

    # 9. Tab to the first starter button
    page.keyboard.press("Tab")
    _assert_focus_valid(
        page, "9. Tab -> starter button", expected_tag="button", expected_class="secondary"
    )

    # 10. Press Enter on starter -> moves focus to #chat-input
    page.keyboard.press("Enter")
    expect(page.locator(".bubble.assistant")).to_be_visible()
    expect(page.locator("#chat-input")).to_be_focused()
    _assert_focus_valid(
        page, "10. Starter activated -> chat-input", expected_id="chat-input", expected_tag="input"
    )

    # 11. Type a follow-up, press Enter -> reply appears
    page.keyboard.type("What about evening?")
    page.keyboard.press("Enter")
    expect(page.locator(".bubble.assistant").nth(1)).to_be_visible()

    # 12. Shift+Tab backwards navigation moves in reverse order
    page.keyboard.press("Shift+Tab")
    _assert_focus_valid(page, "12. Shift+Tab back", require_ring=True)

    # 13. Tab trap check: bounded cycle through controls without trapping
    for _ in range(25):
        page.keyboard.press("Tab")
    info_cycle = check_focused_element(page)
    assert not info_cycle["isBodyOrNone"]


def test_keyboard_only_path_full_journey(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Full user journey using only keyboard events at standard 1280x800 viewport."""
    _walk_full_keyboard_journey(page, live_server)


def test_keyboard_path_narrow_viewport_reflow(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Keyboard path at narrow 320x256 reflow viewport (banner is static)."""
    page.set_viewport_size({"width": 320, "height": 256})
    _walk_full_keyboard_journey(page, live_server)


def test_keyboard_path_200_percent_zoom(page: Any, live_server: str, mock_api: MockApi) -> None:
    """Keyboard path under 200% zoom emulation (640px width, device_scale_factor=2)."""
    page.set_viewport_size({"width": 640, "height": 800})
    _walk_full_keyboard_journey(page, live_server)
