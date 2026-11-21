"""Static checks for the results heading focus and the impact table markup."""

import re

from tests.frontend import CSS, HTML, JS, js_function


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
    body = js_function("renderResult")
    unhide = body.index('byId("result").hidden = false')
    focus = body.index("focusControl(heading)")
    assert unhide < focus
    assert 'var heading = byId("result-h")' in body
    assert re.search(r"if\s*\(\s*plan\s*\)\s*\{\s*focusControl\(heading\);\s*\}", body)
    assert body.count("focusControl(") == 1  # one focus call, none on the reading-only path


def test_result_focus_is_not_stolen_on_error_paths():
    submit = js_function("onGenerate")
    assert "result-h" not in submit
    assert "renderResult(" not in submit  # rendering happens only via the plan event
    # The only calls that reach renderResult are the plan and reading listeners.
    assert JS.count("renderResult(") == 3  # definition + 2 listeners
    assert "result-h" not in js_function("onUseLocation")
    assert "result-h" not in js_function("sendChat")
    assert "result-h" not in js_function("buildChat")
    # Success clears the status and the heading takes over the announcement.
    assert re.search(r'setStatus\(status,\s*""\);\s*publish\("airwise:plan"', submit)


def test_impact_table_has_caption_as_first_child():
    body = js_function("renderImpact")
    assert "IMPACT_CAPTION" in body
    caption = body.index('table.appendChild(el("caption", IMPACT_CAPTION')
    assert body.index('var table = el("table")') < caption < body.index("thead")
    assert caption < body.index("table.appendChild(thead)")
    assert caption < body.index("table.appendChild(tbody)")
    assert body.count("table.appendChild(") == 3  # caption, thead, tbody: caption is first
    assert re.search(r'var IMPACT_CAPTION = "[^"]*approximate\.";', JS)


def test_impact_table_header_cells_have_scope_col():
    body = js_function("renderImpact")
    assert body.count('el("th"') == 1  # every header cell is built in the one loop
    created = body.index('var th = el("th", h)')
    assert (
        created < body.index('th.setAttribute("scope", "col")') < body.index("head.appendChild(th)")
    )


def test_impact_table_wrapper_is_a_named_focusable_region():
    body = js_function("renderImpact")
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
