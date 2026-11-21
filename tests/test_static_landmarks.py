"""Static checks for page landmarks, heading outline, document metadata and the sticky banner."""

import re

from tests.frontend import CSS, HTML, HTMLDocument, declarations


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
    # The disclaimer is a top-level aside landmark direct child of body so its containing block
    # is <body> (allowing position:sticky across page scroll) and all content is within landmarks.
    assert _body_children() == ["a", "aside", "header", "main", "footer", "script"]
    pattern = r"<header>\s*<h1>AirWise</h1>\s*<p>[^<]+</p>\s*</header>"
    assert re.search(pattern, HTML, re.S)


def test_footer_text_is_short_and_only_claims_the_real_data_source():
    footer = re.search(r"<footer\b[^>]*>(.*?)</footer>", HTML, re.S)
    assert footer
    text = re.sub(r"<[^>]+>", "", footer.group(1)).strip()
    assert "not medical advice" in text
    assert "Open-Meteo" in text
    assert len(text) <= 120


def test_disclaimer_landmark_and_parent():
    doc = HTMLDocument(HTML)
    disclaimers = [el for el in doc.elements if "disclaimer" in el.attrs.get("class", "").split()]
    assert len(disclaimers) == 1, "expected exactly one disclaimer element"
    disc = disclaimers[0]
    assert disc.tag == "aside"
    assert disc.attrs.get("aria-label") == "Disclaimer"
    assert disc.parent == "body", (
        "disclaimer containing block must be <body> so position:sticky spans full page height"
    )
    # The base rule (wide and tall viewports) stays sticky; the media query below un-sticks it.
    base = re.search(r"\.disclaimer\s*\{([^}]*)\}", CSS)
    assert base and declarations(base.group(1))["position"] == "sticky"


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
    assert rule and declarations(rule.group(1))["position"] == "static"


def test_scroll_padding_clears_sticky_banner_and_resets_when_static():
    base = re.search(r"(?:^|\s)(?:html|:root)\s*\{([^}]*)\}", CSS)
    assert base, "expected scroll-padding-top on html or :root"
    padding = declarations(base.group(1))["scroll-padding-top"]
    assert re.fullmatch(r"[\d.]+r?em", padding) and float(padding.rstrip("rem")) > 0
    _, block = _small_viewport_media()
    reset = re.search(r"(?:^|\s)(?:html|:root)\s*\{([^}]*)\}", block)
    assert reset and declarations(reset.group(1))["scroll-padding-top"] == "0"


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
