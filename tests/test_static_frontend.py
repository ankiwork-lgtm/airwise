"""Static checks for public/index.html.

Validates: Requirements 1.7, 3.3, 7.7, 11.3, 11.4, 12.2, 15.3
"""

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "public" / "index.html").read_text(
    encoding="utf-8"
)


def test_no_html_injection_sinks():
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML"):
        assert sink not in HTML, sink


def test_no_external_script_or_stylesheet():
    assert not re.search(r"<script\b[^>]*\bsrc\s*=", HTML, re.I)
    for tag in re.findall(r"<link\b[^>]*>", HTML, re.I):
        assert "stylesheet" not in tag.lower(), tag


def test_required_strings_present():
    assert "indicative, not an official declaration" in HTML
    assert "General information only, not medical advice." in HTML
    assert "This is an estimated typical winter value, not live data." in HTML
    assert "This plan is rule-based and not AI-personalized." in HTML


def test_local_storage_access_inside_try():
    accesses = [m.start() for m in re.finditer(r"localStorage\s*\.", HTML)]
    assert accesses
    for pos in accesses:
        line_start = HTML.rfind("\n", 0, pos) + 1
        prefix = HTML[line_start:pos]
        assert re.search(r"\btry\s*\{", prefix), HTML[line_start : line_start + 120]
