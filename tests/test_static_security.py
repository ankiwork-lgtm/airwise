"""Static checks that the frontend has no injection sinks, external assets or inline code."""

import re

from tests.frontend import FRONTEND_TEXT, HTML


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
