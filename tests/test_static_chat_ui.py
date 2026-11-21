"""Static checks for the chat panel's accessibility, speaker labels and history handling."""

import re

from tests.frontend import CSS, HTML, JS, js_function


def test_chat_empty_input_is_announced_and_marked():
    assert 'id="chat-status"' in HTML
    assert 'var CHAT_STATUS_ID = "chat-status"' in JS
    build = js_function("buildChat")
    assert (
        'setStatus(byId(CHAT_STATUS_ID), "Please type a question first.", { error: true })' in build
    )
    assert "markInvalid(input, CHAT_STATUS_ID)" in build
    assert "input.focus()" in build
    assert "unmarkInvalid(input, CHAT_STATUS_ID)" in build
    assert "setStatus(byId(CHAT_STATUS_ID), msg, { error: true })" in js_function("sendChat")


def test_chat_history_is_polite_live_region_without_atomic_reread():
    tag = re.search(r'<ul\b[^>]*\bid="chat-history"[^>]*>', HTML)
    assert tag, "expected a ul with id chat-history"
    assert 'aria-live="polite"' in tag.group(0)
    # aria-atomic would re-read the whole history on each reply.
    assert "aria-atomic" not in tag.group(0)


def test_bubble_speaker_label_is_hidden_text_inserted_before_message():
    body = js_function("addBubble")
    # "You: " for the user; "AirWise (error): " for failed replies; "AirWise: " otherwise.
    assert 'role === "user" ? "You: "' in body
    assert '(failed ? "AirWise (error): " : "AirWise: ")' in body
    assert 'el("span", speaker, "visually-hidden")' in body
    assert "li.insertBefore(" in body and "li.firstChild" in body
    # The label is in the li before it joins the list, so one addition is announced.
    assert body.index("insertBefore(") < body.index("list.appendChild(li)")


def test_bubble_message_is_set_with_text_content_only():
    assert 'el("li", text, ' in js_function("addBubble")
    assert "node.textContent = String(text);" in js_function("el")


def test_speaker_label_never_reaches_history_or_api_payload():
    send = js_function("sendChat")
    assert 'history.push({ role: "user", content: message });' in send
    assert 'history.push({ role: "assistant", content: text });' in send
    for label in ("You: ", "AirWise: ", "AirWise (error)", "speaker"):
        assert label not in send, label
    # addBubble never touches the history array. Comments are stripped first because they
    # mention it, and the lookbehind skips the "chat-history" element id.
    code = re.sub(r"//[^\n]*", "", js_function("addBubble"))
    assert not re.search(r"(?<![\w-])history\b", code)


def _send_chat_handlers() -> tuple[str, str]:
    """Split sendChat's promise handlers into (success handler, rejection handler) source."""
    send = re.sub(r"//[^\n]*", "", js_function("sendChat"))
    start = send.index(".then(function (data) {")
    split = send.index("}, function (e) {", start)
    end = send.index("}).then(function () {", split)
    return send[start:split], send[split:end]


def test_failed_chat_reply_is_shown_but_kept_out_of_history():
    success, _ = _send_chat_handlers()
    # The bubble is added unconditionally, before and outside the history guard.
    assert 'addBubble("assistant", text, failed);' in success
    guard = re.search(r"if\s*\(\s*!failed\s*\)\s*\{(.*?)\n\s*\}\s*$", success, re.S)
    assert guard, "history updates must sit inside `if (!failed) { ... }`"
    assert success.index('addBubble("assistant", text, failed);') < success.index(guard.group(0))
    # Both pushes and the MAX_HISTORY cap are inside the guard, and nowhere else.
    assert 'history.push({ role: "user", content: message });' in guard.group(1)
    assert 'history.push({ role: "assistant", content: text });' in guard.group(1)
    assert "history = history.slice(-MAX_HISTORY);" in guard.group(1)
    outside = success.replace(guard.group(0), "")
    assert "history.push" not in outside
    assert success.count("history.push") == 2


def test_chat_network_error_does_not_touch_history():
    _, rejected = _send_chat_handlers()
    assert 'addBubble("assistant", msg, true);' in rejected
    assert not re.search(r"(?<![\w-])history\b", rejected)


def test_chat_reply_for_an_old_plan_is_dropped_on_new_plan():
    # A reply still in flight when a new plan arrives must not reach the new conversation.
    assert "var generation = chatGeneration;" in js_function("sendChat")
    success, rejected = _send_chat_handlers()
    assert "if (generation !== chatGeneration) { return; }" in success
    assert "if (generation !== chatGeneration) { return; }" in rejected
    plan_listener = re.search(
        r'document\.addEventListener\("airwise:plan", function \(\) \{(.*?)\n  \}\);',
        JS,
        re.S,
    )
    assert plan_listener, "expected the airwise:plan chat reset listener"
    assert "chatGeneration += 1;" in plan_listener.group(1)
    assert "chatBusy = false;" in plan_listener.group(1)


def test_bubble_is_a_containing_block_for_its_label():
    # Without this, the absolutely positioned label escapes the scrolling chat list.
    rule = re.search(r"\.bubble\s*\{([^}]*)\}", CSS)
    assert rule and re.search(r"position\s*:\s*relative\b", rule.group(1))


def test_starter_use_moves_focus_to_chat_input_before_hiding_the_row():
    body = re.sub(r"//[^\n]*", "", js_function("sendChat"))
    guard = body.index(
        'if (chatBusy || !state.plan || message === "" || message.length > MAX_MESSAGE)'
    )
    check = re.search(
        r"if\s*\(\s*starters\.contains\(document\.activeElement\)\s*\)\s*\{\s*focusControl\(input\);\s*\}",
        body,
    )
    assert check, "focus must move to #chat-input only when the focus is inside #starters"
    hide = body.index("starters.hidden = true;")
    assert 'var starters = byId("starters");' in body
    assert 'var input = byId("chat-input");' in body
    # Order: early-return guards, focus move, then hide. A rejected call changes nothing.
    assert guard < check.start() < hide
    assert body.count("focusControl(") == 2
    assert 'byId("starters").hidden = true' not in body


def test_send_moves_focus_to_input_before_disabling_send():
    # A disabled button drops focus to <body>, so focus must leave Send before it is disabled.
    body = re.sub(r"//[^\n]*", "", js_function("sendChat"))
    move = body.index("if (document.activeElement === send) { focusControl(input); }")
    disable = body.index("send.disabled = true;")
    assert move < disable
