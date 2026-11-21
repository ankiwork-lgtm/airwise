"""Static checks for CSS motion, focus, visibility and WCAG contrast rules."""

import re

from tests.frontend import CSS, JS, declarations


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


def test_visually_hidden_class_uses_clip_technique():
    rules = re.findall(r"\.visually-hidden\s*\{([^}]*)\}", CSS)
    assert len(rules) == 1, "expected exactly one .visually-hidden rule"
    decls = declarations(rules[0])
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


def test_focus_visible_rules_cover_interactive_elements_with_min_2px_outline():
    rule_match = re.search(r"([^{]+:focus-visible[^{]*)\{([^}]+)\}", CSS)
    assert rule_match, "expected a :focus-visible rule"
    selectors = rule_match.group(1)
    body = rule_match.group(2)
    for expected in ("button", "input", "select", ".table-wrap"):
        assert expected in selectors, f"expected {expected} in focus-visible selector"
    decls = declarations(body)
    assert "outline" in decls
    outline_width = re.search(r"(\d+)px", decls["outline"])
    assert outline_width and int(outline_width.group(1)) >= 2
    assert "outline-offset" in decls


def test_result_heading_has_explicit_focus_style():
    rule_match = re.search(r"#result-h:(focus|focus-visible)[^{]*\{([^}]+)\}", CSS)
    assert rule_match, "expected explicit focus style on #result-h"
    decls = declarations(rule_match.group(2))
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
    body_decls = declarations(body_rule.group(1))
    body_text = body_decls["color"]
    page_bg = body_decls["background"]
    card_bg = "#fff"

    assert _contrast_ratio(body_text, page_bg) >= 4.5
    assert _contrast_ratio(body_text, card_bg) >= 4.5

    disc_rule = re.search(r"\.disclaimer\s*\{([^}]+)\}", CSS)
    assert disc_rule
    disc_bg = declarations(disc_rule.group(1))["background"]
    assert _contrast_ratio(body_text, disc_bg) >= 4.5

    btn_rule = re.search(r"(?<!\.)\bbutton\s*\{([^}]+)\}", CSS)
    assert btn_rule
    btn_decls = declarations(btn_rule.group(1))
    assert _contrast_ratio(btn_decls["color"], btn_decls["background"]) >= 4.5

    btn_sec_rule = re.search(r"button\.secondary\s*\{([^}]+)\}", CSS)
    assert btn_sec_rule
    btn_sec_decls = declarations(btn_sec_rule.group(1))
    assert _contrast_ratio(btn_sec_decls["color"], btn_sec_decls["background"]) >= 4.5

    input_rule = re.search(r"input\[type=text\][^{]*\{([^}]+)\}", CSS)
    assert input_rule
    input_decls = declarations(input_rule.group(1))
    input_border_match = re.search(r"#([0-9a-fA-F]{3,6})", input_decls["border"])
    assert input_border_match
    assert _contrast_ratio(input_border_match.group(0), card_bg) >= 3.0

    ph_rule = re.search(r"::placeholder\s*\{([^}]+)\}", CSS)
    assert ph_rule
    ph_color = declarations(ph_rule.group(1))["color"]
    assert _contrast_ratio(ph_color, card_bg) >= 4.5

    error_rule = re.search(r"\.status\.error\s*\{([^}]+)\}", CSS)
    assert error_rule
    error_color = declarations(error_rule.group(1))["color"]
    assert _contrast_ratio(error_color, card_bg) >= 4.5
    assert _contrast_ratio(error_color, page_bg) >= 4.5

    muted_rule = re.search(r"\.muted\s*\{([^}]+)\}", CSS)
    assert muted_rule
    muted_color = declarations(muted_rule.group(1))["color"]
    assert _contrast_ratio(muted_color, card_bg) >= 4.5
    assert _contrast_ratio(muted_color, page_bg) >= 4.5

    why_rule = re.search(r"\.why\s*\{([^}]+)\}", CSS)
    assert why_rule
    why_color = declarations(why_rule.group(1))["color"]
    assert _contrast_ratio(why_color, card_bg) >= 4.5

    notice_rule = re.search(r"\.notice\s*\{([^}]+)\}", CSS)
    assert notice_rule
    notice_bg = declarations(notice_rule.group(1))["background"]
    assert _contrast_ratio(body_text, notice_bg) >= 4.5

    user_bubble = re.search(r"\.bubble\.user\s*\{([^}]+)\}", CSS)
    assert user_bubble
    ub_decls = declarations(user_bubble.group(1))
    assert _contrast_ratio(ub_decls["color"], ub_decls["background"]) >= 4.5

    asst_bubble = re.search(r"\.bubble\.assistant\s*\{([^}]+)\}", CSS)
    assert asst_bubble
    asst_bg = declarations(asst_bubble.group(1))["background"]
    assert _contrast_ratio(body_text, asst_bg) >= 4.5

    failed_bubble = re.search(r"\.bubble\.failed\s*\{([^}]+)\}", CSS)
    assert failed_bubble
    fb_decls = declarations(failed_bubble.group(1))
    assert _contrast_ratio(fb_decls["color"], fb_decls["background"]) >= 4.5

    focus_rule = re.search(r":focus-visible\s*\{([^}]+)\}", CSS)
    assert focus_rule
    focus_outline = declarations(focus_rule.group(1))["outline"]
    focus_color_match = re.search(r"#([0-9a-fA-F]{3,6})", focus_outline)
    assert focus_color_match
    focus_color = focus_color_match.group(0)
    assert _contrast_ratio(focus_color, card_bg) >= 3.0
    assert _contrast_ratio(focus_color, page_bg) >= 3.0
    assert _contrast_ratio(focus_color, disc_bg) >= 3.0


def test_skip_link_is_hidden_until_focused_and_has_no_transition():
    rule = re.search(r"\.skip-link\s*\{([^}]*)\}", CSS)
    assert rule, "expected a .skip-link rule"
    decls = declarations(rule.group(1))
    assert decls["position"] == "absolute"
    assert decls["transform"].startswith("translateY(-")  # off-screen by default
    assert int(decls["z-index"]) > 10  # above the sticky disclaimer
    assert "transition" not in decls
    reveal = re.search(r"\.skip-link:focus\s*\{([^}]*)\}", CSS)
    assert reveal and declarations(reveal.group(1))["transform"] == "none"
    # The shared T5.6 ring applies to links, so the revealed link keeps a visible focus ring.
    assert re.search(r"(^|,)\s*a:focus-visible\s*[,{]", CSS, re.M)


def test_skip_link_and_footer_colours_meet_wcag_aa():
    skip = declarations(re.search(r"\.skip-link\s*\{([^}]*)\}", CSS).group(1))
    assert _contrast_ratio(skip["color"], skip["background"]) >= 4.5
    page_bg = declarations(re.search(r"\bbody\s*\{([^}]+)\}", CSS).group(1))["background"]
    disc_bg = declarations(re.search(r"\.disclaimer\s*\{([^}]+)\}", CSS).group(1))["background"]
    ring = re.search(
        r"#[0-9a-fA-F]{3,6}",
        declarations(re.search(r":focus-visible\s*\{([^}]+)\}", CSS).group(1))["outline"],
    ).group(0)
    # The ring sits in the 2px gap outside the link, over the page or the disclaimer.
    assert _contrast_ratio(ring, page_bg) >= 3.0
    assert _contrast_ratio(ring, disc_bg) >= 3.0
    footer = declarations(re.search(r"^\s*footer\s*\{([^}]*)\}", CSS, re.M).group(1))
    assert _contrast_ratio(footer["color"], page_bg) >= 4.5


def test_invalid_fields_have_a_visible_non_colour_cue_that_keeps_the_focus_ring():
    rules = [m for m in re.finditer(r"([^{}]*\[aria-invalid=\"true\"\][^{]*)\{([^}]*)\}", CSS)]
    assert len(rules) == 1, "expected exactly one [aria-invalid] rule"
    selector, decls = rules[0].group(1), declarations(rules[0].group(2))
    assert "input" in selector and "select" in selector
    assert decls["border-color"].lower() == "#b00020"
    # Non-colour cue (WCAG 1.4.1): a thicker border than the 1px default, with padding reduced
    # by the same 1px so the control does not change size.
    default = re.search(r"input\[type=text\],\s*select\s*\{([^}]*)\}", CSS)
    assert default
    default_decls = declarations(default.group(1))
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
    page_bg = declarations(re.search(r"\bbody\s*\{([^}]+)\}", CSS).group(1))["background"]
    assert _contrast_ratio(decls["border-color"], "#fff") >= 3.0
    assert _contrast_ratio(decls["border-color"], page_bg) >= 3.0
