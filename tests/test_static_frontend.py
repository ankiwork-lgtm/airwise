"""Static checks for public/index.html, public/app.css and public/app.js.

Validates: Requirements 1.7, 3.3, 7.7, 11.3, 11.4, 12.2, 15.3
"""

import re

from tests.frontend import CSS, FRONTEND_TEXT, HTML, JS, HTMLDocument


def test_no_html_injection_sinks():
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML"):
        assert sink not in FRONTEND_TEXT, sink


def test_no_external_script_or_stylesheet():
    # Only same-origin, root-relative assets are allowed (T3.7 CSP: 'self').
    allowed = {"/app.js", "/app.css"}
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script\s*>", HTML, re.I | re.S)
    assert scripts, "expected an external script tag"
    for attrs, body in scripts:
        src = re.search(r"\bsrc\s*=\s*[\"']([^\"']*)[\"']", attrs, re.I)
        assert src, attrs
        assert src.group(1) in allowed, src.group(1)
        assert not src.group(1).startswith(("http:", "https:", "//"))
        assert body == "", "inline script body is not allowed"
    stylesheets = [
        tag for tag in re.findall(r"<link\b[^>]*>", HTML, re.I) if "stylesheet" in tag.lower()
    ]
    assert stylesheets, "expected a stylesheet link"
    for tag in stylesheets:
        href = re.search(r"\bhref\s*=\s*[\"']([^\"']*)[\"']", tag, re.I)
        assert href, tag
        assert href.group(1) in allowed, href.group(1)
        assert not href.group(1).startswith(("http:", "https:", "//"))


def test_no_inline_style_or_script_in_html():
    assert not re.search(r"<style\b", HTML, re.I)
    assert not re.search(r"\sstyle\s*=", HTML, re.I)
    assert not re.search(r"\son[a-z]+\s*=", HTML, re.I)
    assert not re.search(r"javascript:", HTML, re.I)


def test_required_strings_present():
    assert "indicative, not an official declaration" in FRONTEND_TEXT
    assert "General information only, not medical advice." in FRONTEND_TEXT
    assert "This is an estimated typical winter value, not live data." in FRONTEND_TEXT
    assert "This plan is rule-based and not AI-personalized." in FRONTEND_TEXT


def test_local_storage_access_inside_try():
    accesses = [m.start() for m in re.finditer(r"localStorage\s*\.", FRONTEND_TEXT)]
    assert accesses
    for pos in accesses:
        line_start = FRONTEND_TEXT.rfind("\n", 0, pos) + 1
        prefix = FRONTEND_TEXT[line_start:pos]
        assert re.search(r"\btry\s*\{", prefix), FRONTEND_TEXT[line_start : line_start + 120]


def _reduced_motion_block() -> str:
    match = re.search(r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{", CSS)
    assert match, "expected a prefers-reduced-motion: reduce media query"
    depth, pos = 1, match.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(CSS[pos], 0)
        pos += 1
    return CSS[match.end() : pos - 1]


def test_reduced_motion_stops_loading_spinner():
    block = _reduced_motion_block()
    rule = re.search(r"\.loading::before\s*\{([^}]*)\}", block)
    assert rule, ".loading::before must be restyled for reduced motion"
    assert re.search(r"animation\s*:\s*none\b", rule.group(1))
    # A static filled indicator, so state is not conveyed by motion alone.
    assert re.search(r"background\s*:", rule.group(1))


def test_reduced_motion_neutralises_other_motion():
    block = _reduced_motion_block()
    assert re.search(r"transition\s*:\s*none\b", block)
    assert re.search(r"scroll-behavior\s*:\s*auto\b", block)


def test_no_smooth_scrolling_in_js():
    assert not re.search(r"behavior\s*:\s*[\"']smooth[\"']", JS)


def _js_function(name: str) -> str:
    """Return the source of `function name(...) { ... }` from app.js."""
    match = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", JS)
    assert match, f"function {name} not found"
    depth, pos = 1, match.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(JS[pos], 0)
        pos += 1
    return JS[match.start() : pos]


def test_status_containers_keep_polite_defaults():
    for node_id in ("status", "geo-status", "chat-status"):
        tag = re.search(r'<div\b[^>]*\bid="' + node_id + r'"[^>]*>', HTML)
        assert tag, node_id
        assert 'role="status"' in tag.group(0), node_id
        assert 'aria-live="polite"' in tag.group(0), node_id


def test_set_status_switches_role_and_live_region():
    body = _js_function("setStatus")
    assert re.search(
        r'setAttribute\(\s*"role"\s*,\s*opts\.error\s*\?\s*"alert"\s*:\s*"status"', body
    )
    assert re.search(
        r'setAttribute\(\s*"aria-live"\s*,\s*opts\.error\s*\?\s*"assertive"\s*:\s*"polite"', body
    )
    # The same node is reused, and the role is set before the text is written.
    assert "createElement" not in body
    assert "replaceChild" not in body
    assert body.index('"role"') < body.index("clearNode(node)") < body.index("appendChild")


def test_invalid_fields_set_aria_invalid_and_append_describedby():
    mark = _js_function("markInvalid")
    assert 'setAttribute("aria-invalid", "true")' in mark
    assert 'tokens(control, "aria-describedby")' in mark
    assert "indexOf(statusId) < 0" in mark  # appended once, never clobbered
    assert 'setAttribute("aria-describedby"' in mark
    unmark = _js_function("unmarkInvalid")
    assert 'removeAttribute("aria-invalid")' in unmark
    assert 'removeAttribute("aria-describedby")' in unmark
    assert "t !== statusId" in unmark  # only our own id is removed


def test_invalid_marks_cleared_on_new_status_and_when_field_fixed():
    assert "clearInvalidFields()" in _js_function("setStatus")
    assert "unmarkInvalid(" in _js_function("revalidateControl")
    init = _js_function("init")
    assert "revalidateControl(id)" in init
    assert '"change"' in init and '"input"' in init


def test_api_field_names_map_to_controls_or_are_skipped():
    body = _js_function("controlIdForApiField")
    assert 'split(".")' in body  # "profile.kids" -> "kids"
    assert ": null;" in body  # unmappable names yield null and are skipped
    assert "describeError" in JS and "fields: Array.isArray(err.fields)" in JS


def test_focus_moves_to_first_invalid_field_on_validation_failure():
    focus = _js_function("focusControl")
    assert ".focus()" in focus
    ids = _js_function("markInvalidIds")
    assert "controlIds().forEach" in ids  # form order decides which is first
    submit = _js_function("onGenerate")
    client = submit.index("invalidFields(profile)")
    assert client < submit.index("focusControl(markInvalidIds(")
    assert re.search(
        r'code\s*===\s*"validation_error"\s*\)\s*\{\s*focusControl\(markApiFields', submit
    )
    # Focus is moved only for validation failures, not for success or other errors.
    assert submit.count("focusControl(") == 2


def test_geolocation_errors_do_not_move_focus():
    assert "focus" not in _js_function("onUseLocation").lower()


def test_chat_empty_input_is_announced_and_marked():
    assert 'id="chat-status"' in HTML
    assert 'var CHAT_STATUS_ID = "chat-status"' in JS
    build = _js_function("buildChat")
    assert (
        'setStatus(byId(CHAT_STATUS_ID), "Please type a question first.", { error: true })' in build
    )
    assert "markInvalid(input, CHAT_STATUS_ID)" in build
    assert "input.focus()" in build
    assert "unmarkInvalid(input, CHAT_STATUS_ID)" in build
    assert "setStatus(byId(CHAT_STATUS_ID), msg, { error: true })" in _js_function("sendChat")


def test_chat_history_is_polite_live_region_without_atomic_reread():
    tag = re.search(r'<ul\b[^>]*\bid="chat-history"[^>]*>', HTML)
    assert tag, "expected a ul with id chat-history"
    assert 'aria-live="polite"' in tag.group(0)
    # aria-atomic would re-read the whole history on each reply.
    assert "aria-atomic" not in tag.group(0)


def test_bubble_speaker_label_is_hidden_text_inserted_before_message():
    body = _js_function("addBubble")
    # "You: " for the user; "AirWise (error): " for failed replies; "AirWise: " otherwise.
    assert 'role === "user" ? "You: "' in body
    assert '(failed ? "AirWise (error): " : "AirWise: ")' in body
    assert 'el("span", speaker, "visually-hidden")' in body
    assert "li.insertBefore(" in body and "li.firstChild" in body
    # The label is in the li before it joins the list, so one addition is announced.
    assert body.index("insertBefore(") < body.index("list.appendChild(li)")


def test_bubble_message_is_set_with_text_content_only():
    assert 'el("li", text, ' in _js_function("addBubble")
    assert "node.textContent = String(text);" in _js_function("el")


def test_speaker_label_never_reaches_history_or_api_payload():
    send = _js_function("sendChat")
    assert 'history.push({ role: "user", content: message });' in send
    assert 'history.push({ role: "assistant", content: text });' in send
    for label in ("You: ", "AirWise: ", "AirWise (error)", "speaker"):
        assert label not in send, label
    # addBubble never touches the history array. Comments are stripped first because they
    # mention it, and the lookbehind skips the "chat-history" element id.
    code = re.sub(r"//[^\n]*", "", _js_function("addBubble"))
    assert not re.search(r"(?<![\w-])history\b", code)


def _send_chat_handlers() -> tuple[str, str]:
    """Split sendChat's promise handlers into (success handler, rejection handler) source."""
    send = re.sub(r"//[^\n]*", "", _js_function("sendChat"))
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


def _declarations(rule_body: str) -> dict[str, str]:
    pairs = (decl.split(":", 1) for decl in rule_body.split(";") if ":" in decl)
    return {prop.strip(): value.strip() for prop, value in pairs}


def test_visually_hidden_class_uses_clip_technique():
    rules = re.findall(r"\.visually-hidden\s*\{([^}]*)\}", CSS)
    assert len(rules) == 1, "expected exactly one .visually-hidden rule"
    decls = _declarations(rules[0])
    assert decls == {
        "position": "absolute",
        "width": "1px",
        "height": "1px",
        "margin": "-1px",
        "padding": "0",
        "overflow": "hidden",
        "clip": "rect(0 0 0 0)",
        "clip-path": "inset(50%)",
        "white-space": "nowrap",
        "border": "0",
    }


def test_bubble_is_a_containing_block_for_its_label():
    # Without this, the absolutely positioned label escapes the scrolling chat list.
    rule = re.search(r"\.bubble\s*\{([^}]*)\}", CSS)
    assert rule and re.search(r"position\s*:\s*relative\b", rule.group(1))


def test_results_heading_is_programmatically_focusable_and_labels_section():
    heading = re.search(r"<h2\b[^>]*\bid=\"result-h\"[^>]*>([^<]*)</h2>", HTML)
    assert heading, "expected an h2 with id result-h"
    assert 'tabindex="-1"' in heading.group(0)
    assert heading.group(1).strip() == "Your air quality plan"
    section = re.search(r"<section\b[^>]*\bid=\"result\"[^>]*>", HTML)
    assert section, "expected the #result section"
    assert 'aria-labelledby="result-h"' in section.group(0)
    assert "aria-label=" not in section.group(0)
    assert re.search(r"\bhidden\b", section.group(0))  # still hidden until rendered
    # The heading sits inside the section it labels, so the hierarchy stays h1 > h2.
    assert re.search(r"<section\b[^>]*\bid=\"result\"[^>]*>\s*<h2\b[^>]*\bid=\"result-h\"", HTML)
    assert len(re.findall(r"\bid=\"result-h\"", HTML)) == 1


def test_result_heading_is_focused_after_unhide_on_plan_render_only():
    body = _js_function("renderResult")
    unhide = body.index('byId("result").hidden = false')
    focus = body.index("focusControl(heading)")
    assert unhide < focus
    assert 'var heading = byId("result-h")' in body
    assert re.search(r"if\s*\(\s*plan\s*\)\s*\{\s*focusControl\(heading\);\s*\}", body)
    assert body.count("focusControl(") == 1  # one focus call, none on the reading-only path


def test_result_focus_is_not_stolen_on_error_paths():
    submit = _js_function("onGenerate")
    assert "result-h" not in submit
    assert "renderResult(" not in submit  # rendering happens only via the plan event
    # The only calls that reach renderResult are the plan and reading listeners.
    assert JS.count("renderResult(") == 3  # definition + 2 listeners
    assert "result-h" not in _js_function("onUseLocation")
    assert "result-h" not in _js_function("sendChat")
    assert "result-h" not in _js_function("buildChat")
    # Success clears the status and the heading takes over the announcement.
    assert re.search(r'setStatus\(status,\s*""\);\s*publish\("airwise:plan"', submit)


def test_impact_table_has_caption_as_first_child():
    body = _js_function("renderImpact")
    assert "IMPACT_CAPTION" in body
    caption = body.index('table.appendChild(el("caption", IMPACT_CAPTION')
    assert body.index('var table = el("table")') < caption < body.index("thead")
    assert caption < body.index("table.appendChild(thead)")
    assert caption < body.index("table.appendChild(tbody)")
    assert body.count("table.appendChild(") == 3  # caption, thead, tbody: caption is first
    assert re.search(r'var IMPACT_CAPTION = "[^"]*approximate\.";', JS)


def test_impact_table_header_cells_have_scope_col():
    body = _js_function("renderImpact")
    assert body.count('el("th"') == 1  # every header cell is built in the one loop
    created = body.index('var th = el("th", h)')
    assert (
        created < body.index('th.setAttribute("scope", "col")') < body.index("head.appendChild(th)")
    )


def test_impact_table_wrapper_is_a_named_focusable_region():
    body = _js_function("renderImpact")
    wrap = body.index('var wrap = el("div", null, "table-wrap")')
    for attr in ('"tabindex", "0"', '"role", "region"', '"aria-labelledby", IMPACT_HEADING_ID'):
        pos = body.index("wrap.setAttribute(" + attr + ")")
        assert wrap < pos < body.index("wrap.appendChild(table)")
    # The name comes from the visible heading, which carries the matching id.
    assert 'var IMPACT_HEADING_ID = "impact-h"' in JS
    assert "heading.id = IMPACT_HEADING_ID" in body
    assert 'var heading = el("h3", "Impact table")' in body
    assert body.index("heading.id") < body.index("if (!rows.length)")
    assert 'id="impact-h"' not in HTML  # created at render time only, so it stays unique


def test_table_wrapper_scrolls_and_keeps_default_focus_outline():
    rule = re.search(r"\.table-wrap\s*\{([^}]*)\}", CSS)
    assert rule and re.search(r"overflow-x\s*:\s*auto", rule.group(1))
    # The only allowed outline removal is the documented #main focus rule (T5.7): main is a
    # programmatic skip-link target, not an interactive control. Anything else is a failure.
    exception = re.search(
        r"/\*(?:(?!\*/).)*programmatic focus target(?:(?!\*/).)*\*/\s*"
        r"#main:focus,\s*#main:focus-visible\s*\{\s*outline\s*:\s*none\s*;\s*\}",
        CSS,
        re.S,
    )
    assert exception, "expected the documented #main focus outline exception"
    remaining = CSS.replace(exception.group(0), "")
    assert not re.search(r"outline\s*:\s*(none|0)\b", remaining)


def test_focus_visible_rules_cover_interactive_elements_with_min_2px_outline():
    rule_match = re.search(r"([^{]+:focus-visible[^{]*)\{([^}]+)\}", CSS)
    assert rule_match, "expected a :focus-visible rule"
    selectors = rule_match.group(1)
    body = rule_match.group(2)
    for expected in ("button", "input", "select", ".table-wrap"):
        assert expected in selectors, f"expected {expected} in focus-visible selector"
    decls = _declarations(body)
    assert "outline" in decls
    outline_width = re.search(r"(\d+)px", decls["outline"])
    assert outline_width and int(outline_width.group(1)) >= 2
    assert "outline-offset" in decls


def test_result_heading_has_explicit_focus_style():
    rule_match = re.search(r"#result-h:(focus|focus-visible)[^{]*\{([^}]+)\}", CSS)
    assert rule_match, "expected explicit focus style on #result-h"
    decls = _declarations(rule_match.group(2))
    assert "outline" in decls
    outline_width = re.search(r"(\d+)px", decls["outline"])
    assert outline_width and int(outline_width.group(1)) >= 2


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_str: str) -> float:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def _contrast_ratio(hex1: str, hex2: str) -> float:
    l1 = _relative_luminance(hex1)
    l2 = _relative_luminance(hex2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def test_wcag_colour_contrast_ratios():
    body_rule = re.search(r"\bbody\s*\{([^}]+)\}", CSS)
    assert body_rule
    body_decls = _declarations(body_rule.group(1))
    body_text = body_decls["color"]
    page_bg = body_decls["background"]
    card_bg = "#fff"

    assert _contrast_ratio(body_text, page_bg) >= 4.5
    assert _contrast_ratio(body_text, card_bg) >= 4.5

    disc_rule = re.search(r"\.disclaimer\s*\{([^}]+)\}", CSS)
    assert disc_rule
    disc_bg = _declarations(disc_rule.group(1))["background"]
    assert _contrast_ratio(body_text, disc_bg) >= 4.5

    btn_rule = re.search(r"(?<!\.)\bbutton\s*\{([^}]+)\}", CSS)
    assert btn_rule
    btn_decls = _declarations(btn_rule.group(1))
    assert _contrast_ratio(btn_decls["color"], btn_decls["background"]) >= 4.5

    btn_sec_rule = re.search(r"button\.secondary\s*\{([^}]+)\}", CSS)
    assert btn_sec_rule
    btn_sec_decls = _declarations(btn_sec_rule.group(1))
    assert _contrast_ratio(btn_sec_decls["color"], btn_sec_decls["background"]) >= 4.5

    input_rule = re.search(r"input\[type=text\][^{]*\{([^}]+)\}", CSS)
    assert input_rule
    input_decls = _declarations(input_rule.group(1))
    input_border_match = re.search(r"#([0-9a-fA-F]{3,6})", input_decls["border"])
    assert input_border_match
    assert _contrast_ratio(input_border_match.group(0), card_bg) >= 3.0

    ph_rule = re.search(r"::placeholder\s*\{([^}]+)\}", CSS)
    assert ph_rule
    ph_color = _declarations(ph_rule.group(1))["color"]
    assert _contrast_ratio(ph_color, card_bg) >= 4.5

    error_rule = re.search(r"\.status\.error\s*\{([^}]+)\}", CSS)
    assert error_rule
    error_color = _declarations(error_rule.group(1))["color"]
    assert _contrast_ratio(error_color, card_bg) >= 4.5
    assert _contrast_ratio(error_color, page_bg) >= 4.5

    muted_rule = re.search(r"\.muted\s*\{([^}]+)\}", CSS)
    assert muted_rule
    muted_color = _declarations(muted_rule.group(1))["color"]
    assert _contrast_ratio(muted_color, card_bg) >= 4.5
    assert _contrast_ratio(muted_color, page_bg) >= 4.5

    why_rule = re.search(r"\.why\s*\{([^}]+)\}", CSS)
    assert why_rule
    why_color = _declarations(why_rule.group(1))["color"]
    assert _contrast_ratio(why_color, card_bg) >= 4.5

    notice_rule = re.search(r"\.notice\s*\{([^}]+)\}", CSS)
    assert notice_rule
    notice_bg = _declarations(notice_rule.group(1))["background"]
    assert _contrast_ratio(body_text, notice_bg) >= 4.5

    user_bubble = re.search(r"\.bubble\.user\s*\{([^}]+)\}", CSS)
    assert user_bubble
    ub_decls = _declarations(user_bubble.group(1))
    assert _contrast_ratio(ub_decls["color"], ub_decls["background"]) >= 4.5

    asst_bubble = re.search(r"\.bubble\.assistant\s*\{([^}]+)\}", CSS)
    assert asst_bubble
    asst_bg = _declarations(asst_bubble.group(1))["background"]
    assert _contrast_ratio(body_text, asst_bg) >= 4.5

    failed_bubble = re.search(r"\.bubble\.failed\s*\{([^}]+)\}", CSS)
    assert failed_bubble
    fb_decls = _declarations(failed_bubble.group(1))
    assert _contrast_ratio(fb_decls["color"], fb_decls["background"]) >= 4.5

    focus_rule = re.search(r":focus-visible\s*\{([^}]+)\}", CSS)
    assert focus_rule
    focus_outline = _declarations(focus_rule.group(1))["outline"]
    focus_color_match = re.search(r"#([0-9a-fA-F]{3,6})", focus_outline)
    assert focus_color_match
    focus_color = focus_color_match.group(0)
    assert _contrast_ratio(focus_color, card_bg) >= 3.0
    assert _contrast_ratio(focus_color, page_bg) >= 3.0
    assert _contrast_ratio(focus_color, disc_bg) >= 3.0


def _body_children() -> list[str]:
    """Return the opening tag names of the direct children of <body>, in order."""
    body = HTML[HTML.index("<body>") + len("<body>") : HTML.index("</body>")]
    tags, depth = [], 0
    for m in re.finditer(r"<(/?)([a-z0-9]+)\b[^>]*>", body, re.I):
        closing, name = m.group(1), m.group(2).lower()
        if name in {"input", "br", "meta", "link"}:
            continue
        if closing:
            depth -= 1
        else:
            if depth == 0:
                tags.append(name)
            depth += 1
    return tags


def test_skip_link_is_first_in_body_and_targets_main():
    first = re.match(r"\s*<body>\s*(<a\b[^>]*>)([^<]*)</a>", HTML[HTML.index("<body>") :])
    assert first, "the skip link must be the very first element in <body>"
    assert 'class="skip-link"' in first.group(1)
    assert 'href="#main"' in first.group(1)
    assert first.group(2) == "Skip to main content"
    assert _body_children()[0] == "a"
    assert len(re.findall(r"\bid=\"main\"", HTML)) == 1
    main_tag = re.search(r"<main\b[^>]*>", HTML)
    assert main_tag and 'id="main"' in main_tag.group(0)
    assert 'tabindex="-1"' in main_tag.group(0)


def test_exactly_one_main_header_footer_landmark_each():
    assert len(re.findall(r"<main\b", HTML)) == 1
    assert len(re.findall(r"<header\b", HTML)) == 1
    assert len(re.findall(r"<footer\b", HTML)) == 1
    # header and footer are direct children of body, so they are banner and contentinfo.
    assert _body_children() == ["a", "div", "header", "main", "footer", "script"]
    assert re.search(r"<header>\s*<h1>AirWise</h1>\s*<p>[^<]+</p>\s*</header>", HTML)


def test_footer_text_is_short_and_only_claims_the_real_data_source():
    footer = re.search(r"<footer\b[^>]*>(.*?)</footer>", HTML, re.S)
    assert footer
    text = re.sub(r"<[^>]+>", "", footer.group(1)).strip()
    assert "not medical advice" in text
    assert "Open-Meteo" in text
    assert len(text) <= 120


def test_disclaimer_note_is_kept():
    assert len(re.findall(r'<div class="disclaimer" role="note">', HTML)) == 1
    # The base rule (wide and tall viewports) stays sticky; the media query below un-sticks it.
    base = re.search(r"\.disclaimer\s*\{([^}]*)\}", CSS)
    assert base and _declarations(base.group(1))["position"] == "sticky"


def _small_viewport_media() -> tuple[str, str]:
    """Return (query, body) of the media query that un-sticks the banner."""
    match = re.search(r"@media\s*([^{]*\b(?:max-width|max-height)\b[^{]*)\{", CSS)
    assert match, "expected a max-width / max-height media query for small viewports"
    depth, pos = 1, match.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(CSS[pos], 0)
        pos += 1
    return match.group(1).strip(), CSS[match.end() : pos - 1]


def test_disclaimer_is_static_on_narrow_and_short_viewports():
    query, block = _small_viewport_media()
    # A comma is "or": either a narrow or a short viewport un-sticks the banner.
    conditions = [c.strip() for c in query.split(",")]
    assert any(re.fullmatch(r"\(\s*max-width\s*:[^)]+\)", c) for c in conditions)
    assert any(re.fullmatch(r"\(\s*max-height\s*:[^)]+\)", c) for c in conditions)
    rule = re.search(r"\.disclaimer\s*\{([^}]*)\}", block)
    assert rule and _declarations(rule.group(1))["position"] == "static"


def test_scroll_padding_clears_sticky_banner_and_resets_when_static():
    base = re.search(r"(?:^|\s)(?:html|:root)\s*\{([^}]*)\}", CSS)
    assert base, "expected scroll-padding-top on html or :root"
    padding = _declarations(base.group(1))["scroll-padding-top"]
    assert re.fullmatch(r"[\d.]+r?em", padding) and float(padding.rstrip("rem")) > 0
    _, block = _small_viewport_media()
    reset = re.search(r"(?:^|\s)(?:html|:root)\s*\{([^}]*)\}", block)
    assert reset and _declarations(reset.group(1))["scroll-padding-top"] == "0"


def test_small_viewport_media_query_uses_relative_units():
    query, _ = _small_viewport_media()
    lengths = re.findall(r":\s*([\d.]+)\s*([a-z%]*)", query)
    assert lengths, query
    assert all(unit in {"em", "rem"} for _, unit in lengths), query
    assert "px" not in query


def test_heading_outline_has_one_h1_and_no_skipped_levels():
    levels = [int(n) for n in re.findall(r"<h([1-6])\b", HTML)]
    assert levels[0] == 1 and levels.count(1) == 1
    assert all(b - a <= 1 for a, b in zip(levels, levels[1:], strict=False))


def test_skip_link_is_hidden_until_focused_and_has_no_transition():
    rule = re.search(r"\.skip-link\s*\{([^}]*)\}", CSS)
    assert rule, "expected a .skip-link rule"
    decls = _declarations(rule.group(1))
    assert decls["position"] == "absolute"
    assert decls["transform"].startswith("translateY(-")  # off-screen by default
    assert int(decls["z-index"]) > 10  # above the sticky disclaimer
    assert "transition" not in decls
    reveal = re.search(r"\.skip-link:focus\s*\{([^}]*)\}", CSS)
    assert reveal and _declarations(reveal.group(1))["transform"] == "none"
    # The shared T5.6 ring applies to links, so the revealed link keeps a visible focus ring.
    assert re.search(r"(^|,)\s*a:focus-visible\s*[,{]", CSS, re.M)


def test_skip_link_and_footer_colours_meet_wcag_aa():
    skip = _declarations(re.search(r"\.skip-link\s*\{([^}]*)\}", CSS).group(1))
    assert _contrast_ratio(skip["color"], skip["background"]) >= 4.5
    page_bg = _declarations(re.search(r"\bbody\s*\{([^}]+)\}", CSS).group(1))["background"]
    disc_bg = _declarations(re.search(r"\.disclaimer\s*\{([^}]+)\}", CSS).group(1))["background"]
    ring = re.search(
        r"#[0-9a-fA-F]{3,6}",
        _declarations(re.search(r":focus-visible\s*\{([^}]+)\}", CSS).group(1))["outline"],
    ).group(0)
    # The ring sits in the 2px gap outside the link, over the page or the disclaimer.
    assert _contrast_ratio(ring, page_bg) >= 3.0
    assert _contrast_ratio(ring, disc_bg) >= 3.0
    footer = _declarations(re.search(r"^\s*footer\s*\{([^}]*)\}", CSS, re.M).group(1))
    assert _contrast_ratio(footer["color"], page_bg) >= 4.5


def test_html_lang_attribute():
    doc = HTMLDocument(HTML)
    html_tags = doc.find_all("html")
    assert len(html_tags) == 1, "expected exactly one <html> element"
    lang = html_tags[0].attrs.get("lang")
    assert lang == "en", f"expected <html lang='en'>, got {lang!r}"


def test_viewport_meta_allows_user_zoom():
    doc = HTMLDocument(HTML)
    metas = [m for m in doc.find_all("meta") if m.attrs.get("name") == "viewport"]
    assert len(metas) == 1, "expected exactly one viewport meta tag"
    content = metas[0].attrs.get("content", "")
    assert "width=device-width" in content
    assert "initial-scale=1" in content
    # WCAG 1.4.4: pinch-zoom must not be blocked or restricted
    assert "user-scalable=no" not in content
    assert "user-scalable=0" not in content
    assert not re.search(r"maximum-scale\s*=\s*[0-4](\.|$)", content)


def test_element_ids_in_html_are_unique():
    doc = HTMLDocument(HTML)
    assert doc.all_ids, "expected element ids in index.html"
    seen: set[str] = set()
    duplicates: list[str] = []
    for elem_id in doc.all_ids:
        if elem_id in seen:
            duplicates.append(elem_id)
        seen.add(elem_id)
    assert not duplicates, f"duplicate element ids found in index.html: {duplicates}"


def test_id_references_integrity_in_html_and_js():
    doc = HTMLDocument(HTML)
    declared_ids = set(doc.all_ids)

    # 1. <label for="..."> references
    labels = doc.find_all("label")
    assert labels, "expected <label> elements in index.html"
    for label in labels:
        target = label.attrs.get("for")
        assert target, f"<label> is missing 'for' attribute: {label.attrs}"
        assert target in declared_ids, f"<label for='{target}'> references nonexistent id"

    # 2. aria-labelledby references in HTML
    for el in doc.elements:
        if "aria-labelledby" in el.attrs:
            for ref_id in el.attrs["aria-labelledby"].split():
                assert ref_id in declared_ids, (
                    f"<{el.tag}> aria-labelledby references nonexistent id: '{ref_id}'"
                )

    # 3. aria-describedby references in HTML
    for el in doc.elements:
        if "aria-describedby" in el.attrs:
            for ref_id in el.attrs["aria-describedby"].split():
                assert ref_id in declared_ids, (
                    f"<{el.tag}> aria-describedby references nonexistent id: '{ref_id}'"
                )

    # 4. In-page fragment hrefs (e.g. skip link href="#main")
    for el in doc.elements:
        href = el.attrs.get("href", "")
        if href.startswith("#"):
            target_id = href[1:]
            assert target_id in declared_ids, f"fragment link '{href}' references nonexistent id"

    # 5. Dynamically created ids in app.js are documented and match
    assert 'var IMPACT_HEADING_ID = "impact-h"' in JS
    assert 'wrap.setAttribute("aria-labelledby", IMPACT_HEADING_ID)' in JS
    assert "heading.id = IMPACT_HEADING_ID" in JS
    assert 'var STATUS_ID = "status"' in JS
    assert 'var CHAT_STATUS_ID = "chat-status"' in JS
    assert "status" in declared_ids
    assert "chat-status" in declared_ids


def test_form_controls_have_associated_labels():
    doc = HTMLDocument(HTML)
    label_for_targets = {
        label.attrs["for"] for label in doc.find_all("label") if "for" in label.attrs
    }

    # All input/select elements in index.html must have an associated <label for>
    form_controls = doc.find_all("input") + doc.find_all("select")
    assert form_controls, "expected form controls in index.html"
    for control in form_controls:
        control_id = control.attrs.get("id")
        assert control_id, f"<{control.tag}> control is missing an id: {control.attrs}"
        assert control_id in label_for_targets, (
            f"<{control.tag} id='{control_id}'> has no matching <label for='{control_id}'>"
        )

    # Dynamic fields generated in app.js: buildForm assigns matching label.htmlFor and select.id
    build_form = _js_function("buildForm")
    assert 'label.htmlFor = "f-" + f.name;' in build_form
    assert 'select.id = "f-" + f.name;' in build_form
    assert "wrap.appendChild(label);" in build_form
    assert "wrap.appendChild(select);" in build_form


def test_button_elements_have_explicit_type():
    doc = HTMLDocument(HTML)
    buttons = doc.find_all("button")
    assert len(buttons) >= 4, "expected at least 4 buttons in index.html"
    for btn in buttons:
        btn_type = btn.attrs.get("type")
        assert btn_type in {"button", "submit", "reset"}, (
            f"<button id='{btn.attrs.get('id')}'> is missing explicit type: {btn.attrs}"
        )

    # Dynamically generated starter buttons in buildChat must set explicit type="button"
    build_chat = _js_function("buildChat")
    assert 'b.type = "button";' in build_chat


def test_no_positive_tabindex_anywhere():
    doc = HTMLDocument(HTML)
    for el in doc.elements:
        if "tabindex" in el.attrs:
            val = el.attrs["tabindex"].strip()
            assert val in {"0", "-1"}, (
                f"<{el.tag}> in index.html has invalid/positive tabindex: {val!r}"
            )

    # In JS: any tabindex set via setAttribute or property assignment must be 0 or -1
    tabindex_calls = re.findall(r'tabindex["\']?\s*,\s*["\']?([^"\')\s]+)', JS, re.I)
    assert tabindex_calls, "expected tabindex assignment in JS"
    for val in tabindex_calls:
        assert val in {"0", "-1"}, f"JS sets invalid/positive tabindex: {val!r}"

    # Also verify no positive tabindex regex matches in JS
    assert not re.search(r"tabIndex\s*=\s*[1-9]", JS)
    assert not re.search(r'setAttribute\s*\(\s*["\']tabindex["\']\s*,\s*["\']?[1-9]', JS)


def test_no_title_only_labelling_on_controls():
    doc = HTMLDocument(HTML)
    # Check that interactive controls do not use title as an accessible name fallback
    interactive_tags = {"input", "select", "button", "a", "textarea"}
    for el in doc.elements:
        if el.tag in interactive_tags:
            assert "title" not in el.attrs, (
                f"<{el.tag}> uses title attribute; use visible text or <label> instead"
            )


def test_live_regions_status_containers_match_set_status():
    doc = HTMLDocument(HTML)
    status_ids = ("status", "geo-status", "chat-status")
    for s_id in status_ids:
        el = doc.find_by_id(s_id)
        assert el is not None, f"status container #{s_id} not found"
        assert el.attrs.get("role") == "status", f"#{s_id} initial role must be 'status'"
        assert el.attrs.get("aria-live") == "polite", f"#{s_id} initial aria-live must be 'polite'"

    chat_history = doc.find_by_id("chat-history")
    assert chat_history is not None, "#chat-history not found"
    assert chat_history.attrs.get("aria-live") == "polite"


def test_textual_cues_for_error_and_failure_states():
    # Errors and failure states must provide textual cues beyond color
    assert "Please complete these fields:" in JS
    assert "We could not get your location. Please enter a city name instead." in JS
    # Chat error bubble adds textual prefix "(error)"
    assert "AirWise (error): " in _js_function("addBubble")
    # Status errors apply .error class alongside role="alert" and descriptive text
    assert 'node.className = "status" + (opts.error ? " error" : "")' in _js_function("setStatus")


def test_starter_use_moves_focus_to_chat_input_before_hiding_the_row():
    body = re.sub(r"//[^\n]*", "", _js_function("sendChat"))
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
    assert body.count("focusControl(") == 1
    assert 'byId("starters").hidden = true' not in body


def test_invalid_fields_have_a_visible_non_colour_cue_that_keeps_the_focus_ring():
    rules = [m for m in re.finditer(r"([^{}]*\[aria-invalid=\"true\"\][^{]*)\{([^}]*)\}", CSS)]
    assert len(rules) == 1, "expected exactly one [aria-invalid] rule"
    selector, decls = rules[0].group(1), _declarations(rules[0].group(2))
    assert "input" in selector and "select" in selector
    assert decls["border-color"].lower() == "#b00020"
    # Non-colour cue (WCAG 1.4.1): a thicker border than the 1px default, with padding reduced
    # by the same 1px so the control does not change size.
    default = re.search(r"input\[type=text\],\s*select\s*\{([^}]*)\}", CSS)
    assert default
    default_decls = _declarations(default.group(1))
    assert default_decls["border"].startswith("1px")
    assert default_decls["padding"] == "8px"
    assert decls["border-width"] == "2px"
    assert decls["padding"] == "7px"
    # The :focus-visible ring is neither overridden nor removed by the invalid style.
    assert not any(prop.startswith("outline") for prop in decls)
    assert not re.search(
        r"outline\s*:\s*(none|0)\b", CSS.replace("#main:focus-visible { outline: none; }", "")
    )
    # The border keeps non-text contrast on the white field and on the page background.
    page_bg = _declarations(re.search(r"\bbody\s*\{([^}]+)\}", CSS).group(1))["background"]
    assert _contrast_ratio(decls["border-color"], "#fff") >= 3.0
    assert _contrast_ratio(decls["border-color"], page_bg) >= 3.0
