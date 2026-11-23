"""Browser tests for the follow-up chat: send, starters, guards, failures, history and reset."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest
from playwright.sync_api import expect

from airwise.models import ChatRequest
from tests.browser.helpers import fill_valid_form
from tests.frontend import JS

if TYPE_CHECKING:
    from tests.browser.conftest import MockApi

EXPLICIT_TIMEOUT_MS = 5000
CHAT_REPLY = "Keep windows closed during the early morning peak."
SEND_LABEL = "Send"
INPUT_LABEL = "Your question"


def _starters_from_source() -> list[str]:
    """Reads the STARTERS array from app.js so the test follows the list instead of copying it."""
    match = re.search(r"const STARTERS = \[(.*?)\];", JS, re.S)
    assert match, "STARTERS array not found in app.js"
    labels = re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))
    assert len(labels) == 4
    return labels


STARTERS = _starters_from_source()


def render_plan(page: Any, live_server: str, city: str = "Delhi") -> None:
    """Renders a plan through the real form (mock_api answers /api/plan) and waits for the chat."""
    page.goto(live_server)
    fill_valid_form(page, city=city)
    page.get_by_role("button", name="Generate plan").click()
    expect(page.locator("#chat")).to_be_visible(timeout=EXPLICIT_TIMEOUT_MS)


def chat_requests(mock_api: MockApi) -> list[Any]:
    return [r for r in mock_api.requests if "/api/chat" in r.url]


def bubbles(page: Any) -> Any:
    return page.locator("#chat-history > li")


def send_button(page: Any) -> Any:
    return page.get_by_role("button", name=SEND_LABEL, exact=True)


def chat_input(page: Any) -> Any:
    return page.get_by_label(INPUT_LABEL)


def _tab_until_focused(page: Any, target: Any, limit: int = 80) -> None:
    """Presses Tab with the real keyboard until `target` has focus (bounded, no waits)."""
    for _ in range(limit):
        if target.evaluate("el => el === document.activeElement"):
            return
        page.keyboard.press("Tab")
    raise AssertionError("Tab order never reached the target control")


def _active_id(page: Any) -> str | None:
    return page.evaluate("() => document.activeElement ? document.activeElement.id : null")


# a. Visibility and labels
def test_chat_hidden_before_plan_and_visible_after_with_labelled_controls(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """The chat is hidden until a plan renders; starters come from app.js; controls are labelled."""
    page.goto(live_server)
    expect(page.locator("#chat")).to_be_hidden()
    expect(page.locator("#starters")).to_be_hidden()

    render_plan(page, live_server)
    expect(page.get_by_role("region", name="Ask a follow-up")).to_be_visible()
    expect(page.locator("#starters")).to_be_visible()
    expect(page.locator("#starters button")).to_have_text(STARTERS)
    for label in STARTERS:
        expect(page.get_by_role("button", name=label, exact=True)).to_be_visible()

    expect(chat_input(page)).to_be_visible()
    expect(chat_input(page)).to_have_attribute("maxlength", "500")
    expect(send_button(page)).to_be_enabled()
    assert chat_requests(mock_api) == []


# b. Send by typing
def test_typed_question_sends_once_and_shows_user_then_assistant_bubble(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Enter sends; the input clears; Send is disabled until the reply; a second send is dropped."""
    render_plan(page, live_server)
    mock_api.set_chat({"reply": CHAT_REPLY, "failed": False})
    gate = mock_api.hold("chat")

    chat_input(page).fill("  Is my plan enough?  ")
    chat_input(page).press("Enter")

    expect(bubbles(page)).to_have_count(1)
    expect(bubbles(page).nth(0)).to_have_text("You: Is my plan enough?")
    expect(chat_input(page)).to_have_value("")
    expect(chat_input(page)).to_be_focused()
    expect(page.locator("#starters")).to_be_hidden()

    # Pending: Send is disabled and a second Enter or click sends nothing.
    expect(send_button(page)).to_be_disabled()
    chat_input(page).fill("A second question")
    chat_input(page).press("Enter")
    page.evaluate("() => document.getElementById('chat-send').click()")
    assert len(chat_requests(mock_api)) == 1
    expect(bubbles(page)).to_have_count(1)
    # The unsent text stays in the input rather than being lost.
    expect(chat_input(page)).to_have_value("A second question")

    gate.release()
    expect(bubbles(page)).to_have_count(2, timeout=EXPLICIT_TIMEOUT_MS)
    expect(bubbles(page).nth(1)).to_have_text(f"AirWise: {CHAT_REPLY}")
    expect(send_button(page)).to_be_enabled()

    requests = chat_requests(mock_api)
    assert len(requests) == 1
    body = requests[0].json
    assert set(body) == {"message", "history", "plan", "reading", "profile"}
    assert body["message"] == "Is my plan enough?"
    assert body["history"] == []
    assert body["profile"]["city"] == "Delhi"
    ChatRequest.model_validate(body)


# c. Starter questions via the real keyboard
@pytest.mark.parametrize("key", ["Enter", "Space"])
def test_starter_activated_by_keyboard_sends_and_moves_focus_to_input(
    page: Any, live_server: str, mock_api: MockApi, key: str
) -> None:
    """Tab to a starter, press Enter or Space: it is sent, the row hides, focus goes to input."""
    render_plan(page, live_server)
    question = STARTERS[0]
    starter = page.get_by_role("button", name=question, exact=True)
    _tab_until_focused(page, starter)

    page.keyboard.press(key)

    expect(bubbles(page).nth(0)).to_have_text(f"You: {question}")
    expect(page.locator("#starters")).to_be_hidden()
    expect(chat_input(page)).to_be_focused()
    assert _active_id(page) == "chat-input"
    expect(bubbles(page)).to_have_count(2, timeout=EXPLICIT_TIMEOUT_MS)
    expect(chat_input(page)).to_be_focused()

    requests = chat_requests(mock_api)
    assert len(requests) == 1
    assert requests[0].json["message"] == question
    assert requests[0].json["history"] == []


def test_starter_mouse_click_sends_and_ends_focus_in_chat_input(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """A mouse click on a starter sends it. The click first focuses the button, then sendChat moves
    focus to #chat-input before the row hides, so focus does not fall to <body>."""
    render_plan(page, live_server)
    question = STARTERS[2]
    page.get_by_role("button", name=question, exact=True).click()

    expect(bubbles(page).nth(0)).to_have_text(f"You: {question}")
    expect(page.locator("#starters")).to_be_hidden()
    expect(chat_input(page)).to_be_focused()
    assert _active_id(page) == "chat-input"
    expect(bubbles(page)).to_have_count(2, timeout=EXPLICIT_TIMEOUT_MS)
    assert chat_requests(mock_api)[0].json["message"] == question


# d. Send from the form keeps focus in the form
def test_send_button_click_keeps_focus_inside_the_chat_form(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Clicking Send with a typed question leaves focus inside the chat form, not on <body>."""
    render_plan(page, live_server)
    gate = mock_api.hold("chat")
    chat_input(page).fill("Is it safe to walk to school?")
    send_button(page).click()

    expect(send_button(page)).to_be_disabled()
    focus_in_form = page.evaluate(
        "() => document.getElementById('chat-form').contains(document.activeElement)"
    )
    assert focus_in_form, f"focus left the chat form: {_active_id(page)}"

    gate.release()
    expect(bubbles(page)).to_have_count(2, timeout=EXPLICIT_TIMEOUT_MS)
    expect(send_button(page)).to_be_enabled()
    assert _active_id(page) != "body"


def ask(page: Any, mock_api: MockApi, question: str, reply: str, *, failed: bool = False) -> None:
    """Sends one question with a mocked reply and waits until its reply bubble is shown."""
    before = bubbles(page).count()
    mock_api.set_chat({"reply": reply, "failed": failed})
    chat_input(page).fill(question)
    chat_input(page).press("Enter")
    expect(bubbles(page)).to_have_count(before + 2, timeout=EXPLICIT_TIMEOUT_MS)
    expect(send_button(page)).to_be_enabled()


# e. Guards
@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "whitespace-only"])
def test_blank_question_is_refused_with_alert_and_marked_input(
    page: Any, live_server: str, mock_api: MockApi, value: str
) -> None:
    """Enter on a blank input sends nothing, announces the error and marks and focuses the input."""
    render_plan(page, live_server)
    chat_input(page).fill(value)
    chat_input(page).press("Enter")

    status = page.locator("#chat-status")
    expect(status).to_have_text("Please type a question first.")
    expect(status).to_have_attribute("role", "alert")
    expect(chat_input(page)).to_have_attribute("aria-invalid", "true")
    expect(chat_input(page)).to_be_focused()
    expect(bubbles(page)).to_have_count(0)
    assert chat_requests(mock_api) == []


def test_typing_after_blank_refusal_clears_the_invalid_mark(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """The invalid mark is removed as soon as the input holds a non-blank value."""
    render_plan(page, live_server)
    chat_input(page).press("Enter")
    expect(chat_input(page)).to_have_attribute("aria-invalid", "true")

    chat_input(page).fill("W")
    expect(chat_input(page)).not_to_have_attribute("aria-invalid", "true")
    assert "chat-status" not in (chat_input(page).get_attribute("aria-describedby") or "")
    assert chat_requests(mock_api) == []


def test_over_long_question_is_not_sent_and_text_is_kept(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """The input has maxlength=500, so a 501-character value is set by script. Nothing is sent."""
    render_plan(page, live_server)
    long_text = "x" * 501
    page.evaluate(
        "([id, value]) => { document.getElementById(id).value = value; }",
        ["chat-input", long_text],
    )
    chat_input(page).press("Enter")

    # The send is ignored, so the typed text stays in the input and no bubble is added.
    expect(chat_input(page)).to_have_value(long_text)
    expect(bubbles(page)).to_have_count(0)
    assert chat_requests(mock_api) == []
    assert send_button(page).is_enabled()


# f. Failure bubble and history
def test_failed_reply_shows_error_bubble_and_is_left_out_of_history(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """A 200 with failed: true is an error bubble; later requests carry only successful turns."""
    render_plan(page, live_server)
    failure = "Sorry, an answer is unavailable right now. Please try again later."
    ask(page, mock_api, "First question", failure, failed=True)

    failed_bubble = bubbles(page).nth(1)
    expect(failed_bubble).to_have_text(f"AirWise (error): {failure}")
    expect(failed_bubble).to_have_class("bubble assistant failed")

    ask(page, mock_api, "Second question", "Good answer two.")
    requests = chat_requests(mock_api)
    assert len(requests) == 2
    assert requests[1].json["history"] == []

    ask(page, mock_api, "Third question", "Good answer three.")
    assert chat_requests(mock_api)[2].json["history"] == [
        {"role": "user", "content": "Second question"},
        {"role": "assistant", "content": "Good answer two."},
    ]


def test_successful_exchanges_accumulate_in_order_with_role_and_content_only(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Two successful exchanges give four history items, in order, with no speaker prefix."""
    render_plan(page, live_server)
    ask(page, mock_api, "Question one", "Reply one.")
    ask(page, mock_api, "Question two", "Reply two.")
    ask(page, mock_api, "Question three", "Reply three.")

    history = chat_requests(mock_api)[2].json["history"]
    assert history == [
        {"role": "user", "content": "Question one"},
        {"role": "assistant", "content": "Reply one."},
        {"role": "user", "content": "Question two"},
        {"role": "assistant", "content": "Reply two."},
    ]
    for turn in history:
        assert set(turn) == {"role", "content"}
        assert not turn["content"].startswith(("You: ", "AirWise: "))
    ChatRequest.model_validate(chat_requests(mock_api)[2].json)


# g. HTTP and network errors
@pytest.mark.parametrize(
    ("status", "body", "headers", "message"),
    [
        (
            500,
            {"error": {"code": "server_error", "message": "boom", "fields": []}},
            {},
            "Something went wrong on our side. Please try again later.",
        ),
        (
            422,
            {"error": {"code": "validation_error", "message": "x", "fields": ["message"]}},
            {},
            "Some details were not accepted. Please fix the fields listed below.",
        ),
        (
            429,
            {"error": {"code": "rate_limited", "message": "Too many.", "fields": []}},
            {"Retry-After": "9"},
            "Too many requests. Please try again in 9 seconds.",
        ),
    ],
    ids=["500-envelope", "422-envelope", "429-retry-after"],
)
def test_chat_http_error_shows_error_bubble_and_alert_then_retry_succeeds(
    page: Any,
    live_server: str,
    mock_api: MockApi,
    status: int,
    body: dict[str, Any],
    headers: dict[str, str],
    message: str,
) -> None:
    """An HTTP error adds an error bubble and a generic alert, keeps history, and allows a retry."""
    render_plan(page, live_server)
    ask(page, mock_api, "Before the error", "Earlier reply.")
    mock_api.set_chat(body, status=status, headers=headers)

    chat_input(page).fill("Trigger the error")
    chat_input(page).press("Enter")

    expect(bubbles(page)).to_have_count(4, timeout=EXPLICIT_TIMEOUT_MS)
    expect(bubbles(page).nth(3)).to_have_text(f"AirWise (error): {message}")
    expect(bubbles(page).nth(3)).to_have_class("bubble assistant failed")
    status_node = page.locator("#chat-status")
    expect(status_node).to_have_text(message)
    expect(status_node).to_have_attribute("role", "alert")
    expect(send_button(page)).to_be_enabled()
    assert "Traceback" not in status_node.inner_text()

    # Retry with a working reply: history holds only the earlier successful exchange.
    ask(page, mock_api, "Retry question", "Recovered reply.")
    retry = chat_requests(mock_api)[-1].json
    assert retry["message"] == "Retry question"
    assert retry["history"] == [
        {"role": "user", "content": "Before the error"},
        {"role": "assistant", "content": "Earlier reply."},
    ]
    expect(status_node).to_have_text("")


def test_chat_network_failure_shows_error_bubble_and_alert(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """An aborted request shows the connection message in a bubble and in the alert."""
    render_plan(page, live_server)
    gate = mock_api.hold("chat")
    chat_input(page).fill("Offline question")
    chat_input(page).press("Enter")
    expect(send_button(page)).to_be_disabled()

    gate.release(abort=True)

    message = "Could not reach AirWise. Check your connection and try again."
    expect(bubbles(page).nth(1)).to_have_text(f"AirWise (error): {message}")
    status_node = page.locator("#chat-status")
    expect(status_node).to_have_text(message)
    expect(status_node).to_have_attribute("role", "alert")
    expect(send_button(page)).to_be_enabled()


# h. History cap
def test_history_sent_is_capped_at_ten_and_keeps_the_newest_turns(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """After eight exchanges the last request carries only the newest ten history items."""
    render_plan(page, live_server)
    for i in range(1, 9):
        ask(page, mock_api, f"Question {i}", f"Reply {i}.")

    # Request 8 is sent with exchanges 1-7 in history (14 items). Capped to 10: exchanges 3-7.
    history = chat_requests(mock_api)[-1].json["history"]
    assert len(history) == 10
    expected = []
    for i in range(3, 8):
        expected.append({"role": "user", "content": f"Question {i}"})
        expected.append({"role": "assistant", "content": f"Reply {i}."})
    assert history == expected
    ChatRequest.model_validate(chat_requests(mock_api)[-1].json)


# i. Reset after a new plan
def _second_plan(mock_api: MockApi) -> dict[str, Any]:
    """A plan response that differs from the default one in the reading and the exposure score."""
    second: dict[str, Any] = json.loads(json.dumps(mock_api.plan_response))
    second["reading"]["location_name"] = "Pune"
    second["reading"]["aqi"] = 120
    second["plan"]["exposure_score"] = 12.0
    return second


def test_new_plan_resets_chat_and_next_request_uses_the_new_plan(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """A new plan empties the conversation, shows starters, clears status and uses the new plan."""
    render_plan(page, live_server, city="Delhi")
    ask(page, mock_api, "Old question", "Old reply.")
    mock_api.set_plan(_second_plan(mock_api))

    fill_valid_form(page, city="Pune")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(
        timeout=EXPLICIT_TIMEOUT_MS
    )

    expect(bubbles(page)).to_have_count(0)
    expect(page.locator("#starters")).to_be_visible()
    expect(page.locator("#starters button")).to_have_count(len(STARTERS))
    expect(page.locator("#chat-status")).to_have_text("")

    ask(page, mock_api, "New question", "New reply.")
    body = chat_requests(mock_api)[-1].json
    expected = _second_plan(mock_api)
    assert body["history"] == []
    assert body["plan"] == expected["plan"]
    assert body["reading"] == expected["reading"]
    assert body["profile"]["city"] == "Pune"
    ChatRequest.model_validate(body)


def test_chat_reply_in_flight_during_new_plan_does_not_land_in_new_conversation(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """A reply that arrives after a new plan must not show up in the new chat or its history."""
    render_plan(page, live_server, city="Delhi")
    gate = mock_api.hold("chat")
    chat_input(page).fill("Question for the old plan")
    chat_input(page).press("Enter")
    expect(send_button(page)).to_be_disabled()

    mock_api.set_plan(_second_plan(mock_api))
    fill_valid_form(page, city="Pune")
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(
        timeout=EXPLICIT_TIMEOUT_MS
    )

    gate.release()
    # Send is re-enabled only after the old reply's handlers have run, so this wait is the signal.
    expect(send_button(page)).to_be_enabled(timeout=EXPLICIT_TIMEOUT_MS)
    expect(bubbles(page)).to_have_count(0)
    ask(page, mock_api, "New question", "New reply.")
    assert chat_requests(mock_api)[-1].json["history"] == []


# j. Hostile content
HOSTILE_REPLY = "<img src=x onerror=alert(1)><script>window.__pwned=1</script>"
HOSTILE_QUESTION = '<img src=x onerror="window.__pwned=2"><b>bold?</b>'


def test_hostile_reply_and_question_render_as_text_only(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """Markup in a reply or question is shown as text: no img or script element, no global runs."""
    render_plan(page, live_server)
    ask(page, mock_api, HOSTILE_QUESTION, HOSTILE_REPLY)

    expect(bubbles(page).nth(0)).to_have_text(f"You: {HOSTILE_QUESTION}")
    expect(bubbles(page).nth(1)).to_have_text(f"AirWise: {HOSTILE_REPLY}")
    history = page.locator("#chat-history")
    assert history.locator("img, script, b").count() == 0
    assert page.evaluate("() => window.__pwned") is None
    assert page.locator("img[src='x']").count() == 0


def test_long_unbroken_text_wraps_and_does_not_overflow_the_history(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """A 500-character run with no spaces wraps inside the list instead of scrolling it sideways."""
    render_plan(page, live_server)
    long_run = "W" * 500
    ask(page, mock_api, long_run, "Short reply.")

    overflow = page.evaluate(
        """() => {
            const list = document.getElementById('chat-history');
            return { scroll: list.scrollWidth, client: list.clientWidth };
        }"""
    )
    assert overflow["scroll"] <= overflow["client"], overflow


# k. Accessibility in the real browser
def test_history_is_a_polite_live_region_and_each_bubble_is_added_once(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """The list is polite, and each message adds exactly one item (no duplicates or re-reads)."""
    render_plan(page, live_server)
    history = page.locator("#chat-history")
    expect(history).to_have_attribute("aria-live", "polite")
    expect(history).not_to_have_attribute("aria-atomic", "true")

    ask(page, mock_api, "First", "Reply one.")
    expect(bubbles(page)).to_have_count(2)
    ask(page, mock_api, "Second", "Reply two.")
    expect(bubbles(page)).to_have_count(4)
    expect(bubbles(page).nth(3)).to_have_text("AirWise: Reply two.")


def test_speaker_prefix_is_visually_hidden_but_present_in_text(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """The 'You: ' prefix is clipped to a 1 by 1 box, yet it is part of the bubble's text."""
    render_plan(page, live_server)
    ask(page, mock_api, "Visible text", "Reply text.")

    prefix = bubbles(page).nth(0).locator(".visually-hidden")
    expect(prefix).to_have_text("You: ")
    box = prefix.bounding_box()
    assert box is not None
    assert box["width"] <= 1 and box["height"] <= 1, box
    expect(bubbles(page).nth(1).locator(".visually-hidden")).to_have_text("AirWise: ")
    expect(bubbles(page).nth(0)).to_contain_text("You: Visible text")


def test_chat_region_is_named_by_its_heading(
    page: Any, live_server: str, mock_api: MockApi
) -> None:
    """The chat section is a named region (aria-labelledby its h2), and its input has a label."""
    render_plan(page, live_server)
    region = page.get_by_role("region", name="Ask a follow-up")
    expect(region).to_be_visible()
    expect(region.get_by_role("heading", name="Ask a follow-up")).to_be_visible()
    expect(chat_input(page)).to_have_accessible_name(INPUT_LABEL)
    expect(send_button(page)).to_have_accessible_name(SEND_LABEL)
