"""Static checks for unique ids, id references, tabindex, live regions and textual cues."""

import re

from tests.frontend import HTML, JS, HTMLDocument, js_function


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
    assert 'const IMPACT_HEADING_ID = "impact-h"' in JS
    assert 'wrap.setAttribute("aria-labelledby", IMPACT_HEADING_ID)' in JS
    assert "heading.id = IMPACT_HEADING_ID" in JS
    assert 'const STATUS_ID = "status"' in JS
    assert 'const CHAT_STATUS_ID = "chat-status"' in JS
    assert "status" in declared_ids
    assert "chat-status" in declared_ids


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
    assert "AirWise (error): " in js_function("addBubble")
    # Status errors apply .error class alongside role="alert" and descriptive text
    assert 'node.className = "status" + (opts.error ? " error" : "")' in js_function("setStatus")
