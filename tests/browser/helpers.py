"""Shared helpers for browser tests (form filling, geolocation stub, saved-profile seeding)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import expect

STORAGE_KEY = "airwise.profile"
AXE_VENDOR_PATH = Path(__file__).parent / "vendor" / "axe.min.js"
EXPECTED_AXE_SHA256 = "29348999450cdf2849a8e70b7912fc2da85a849da39c0d0d5394f51d4a9ed95c"
DEFAULT_AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]

# Replaces navigator.geolocation with a stub that records calls and lets the test decide
# when (and how) each request ends. This keeps tests deterministic and independent of any
# real device location or native permission prompt.
GEOLOCATION_STUB = """
window.__geo = {
    calls: [],
    last() { return this.calls[this.calls.length - 1]; },
    succeed(lat, lon) {
        this.last().success({
            coords: { latitude: lat, longitude: lon, accuracy: 10 },
            timestamp: 0,
        });
    },
    fail(code) {
        this.last().error({ code: code, message: 'stub' });
    },
};
Object.defineProperty(navigator, 'geolocation', {
    configurable: true,
    value: {
        getCurrentPosition(success, error, options) {
            window.__geo.calls.push({ success: success, error: error, options: options });
        },
        watchPosition() { return 0; },
        clearWatch() {},
    },
});
"""

NO_GEOLOCATION = """
Object.defineProperty(navigator, 'geolocation', { configurable: true, value: undefined });
"""


def fill_profile_selects(page: Any, *, last: bool = False) -> dict[str, str]:
    """Selects a non-empty option (first, or last if `last`) in every profile select."""
    selected_values: dict[str, str] = {}
    selects = page.locator("#fields select").all()
    for select in selects:
        field_id = select.get_attribute("id")
        assert field_id is not None
        values = [
            v for v in (o.get_attribute("value") for o in select.locator("option").all()) if v
        ]
        val = values[-1] if last else values[0]
        select.select_option(val)
        selected_values[field_id] = val
    return selected_values


def fill_valid_form(page: Any, city: str = "Delhi", *, last: bool = False) -> dict[str, str]:
    """Fills the city and dynamically selects an option for all profile fields."""
    page.get_by_label("City").fill(city)
    return fill_profile_selects(page, last=last)


def stored_profile(page: Any) -> dict[str, Any] | None:
    """Returns the parsed saved profile, or None when the key is absent."""
    raw = page.evaluate("(key) => window.localStorage.getItem(key)", STORAGE_KEY)
    return None if raw is None else json.loads(raw)


def seed_storage(page: Any, raw: str) -> None:
    """Writes a raw string under the saved-profile key (the caller reloads the page)."""
    page.evaluate("([key, raw]) => window.localStorage.setItem(key, raw)", [STORAGE_KEY, raw])


def geo_succeed(page: Any, lat: float, lon: float) -> None:
    page.evaluate("([lat, lon]) => window.__geo.succeed(lat, lon)", [lat, lon])


def geo_fail(page: Any, code: int) -> None:
    page.evaluate("(code) => window.__geo.fail(code)", code)


def save_real_profile(page: Any, live_server: str, city: str = "Delhi") -> dict[str, Any]:
    """Runs the real save path once (fill, Generate) and returns what was saved.

    Returns {"profile": parsed saved JSON, "selects": {select id: chosen value}}. Requires the
    mock_api fixture to be active so /api/plan is answered.
    """
    page.goto(live_server)
    selects = fill_valid_form(page, city=city, last=True)
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_role("heading", name="Your air quality plan")).to_be_visible(timeout=5000)
    saved = stored_profile(page)
    assert saved is not None
    return {"profile": saved, "selects": selects}


def get_vendored_axe_source() -> str:
    """Reads the vendored axe.min.js script from disk."""
    if not AXE_VENDOR_PATH.exists():
        raise FileNotFoundError(f"Vendored axe-core not found at {AXE_VENDOR_PATH}")
    return AXE_VENDOR_PATH.read_text(encoding="utf-8")


def run_axe(
    page: Any,
    *,
    tags: list[str] | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Injects vendored axe-core and executes a scan on the page DOM."""
    axe_source = get_vendored_axe_source()
    page.evaluate(axe_source)
    run_tags = tags if tags is not None else DEFAULT_AXE_TAGS
    options = {
        "runOnly": {
            "type": "tag",
            "values": run_tags,
        }
    }
    target_expr = context if context is not None else "document"
    res: dict[str, Any] = page.evaluate(
        f"([target, opts]) => axe.run({target_expr}, opts)",
        [context, options],
    )
    return res


def format_axe_violations(violations: list[dict[str, Any]]) -> str:
    """Formats axe violations into a detailed, actionable failure message."""
    lines = [f"Found {len(violations)} accessibility violation(s):"]
    for i, v in enumerate(violations, 1):
        impact = v.get("impact", "unknown").upper()
        lines.append(f"\n{i}. [{impact}] {v.get('id')}: {v.get('help')}")
        lines.append(f"   Description: {v.get('description')}")
        lines.append(f"   Help URL: {v.get('helpUrl')}")
        for node in v.get("nodes", []):
            lines.append(f"   - Target: {node.get('target')}")
            lines.append(f"     HTML: {node.get('html')}")
            if node.get("failureSummary"):
                lines.append(f"     Summary: {node.get('failureSummary')}")
    return "\n".join(lines)


def assert_no_axe_violations(
    results: dict[str, Any],
    *,
    allowed_rule_ids: set[str] | None = None,
) -> None:
    """Asserts that the axe scan returned zero violations (except explicitly allow-listed rules)."""
    violations = results.get("violations", [])
    if allowed_rule_ids:
        violations = [v for v in violations if v.get("id") not in allowed_rule_ids]
    if violations:
        raise AssertionError(format_axe_violations(violations))


def check_focused_element(page: Any) -> dict[str, Any]:
    """Inspects the active element for focus ring, visibility, and obstruction."""
    return page.evaluate(
        """() => {
        const el = document.activeElement;
        if (!el || el === document.body || el === document.documentElement) {
            return {
                tag: el ? el.tagName : 'none',
                id: '',
                className: '',
                isBodyOrNone: true,
                outlineWidth: 0,
                outlineStyle: 'none',
                boxShadow: 'none',
                hasFocusRing: false,
                inViewport: false,
                notCovered: false,
            };
        }
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        const outlineWidth = parseFloat(style.outlineWidth) || 0;
        const outlineStyle = style.outlineStyle;
        const boxShadow = style.boxShadow;
        const hasRing = (outlineWidth >= 2 && outlineStyle !== 'none') ||
            (boxShadow && boxShadow !== 'none');

        const inViewport = rect.top < window.innerHeight &&
            rect.bottom > 0 && rect.left < window.innerWidth && rect.right > 0;

        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        let notCovered = true;
        if (cx >= 0 && cx <= window.innerWidth && cy >= 0 && cy <= window.innerHeight) {
            const topEl = document.elementFromPoint(cx, cy);
            notCovered = !!topEl && (topEl === el || el.contains(topEl) || topEl.contains(el));
        }

        return {
            tag: el.tagName,
            id: el.id || '',
            className: el.className || '',
            isBodyOrNone: false,
            outlineWidth: outlineWidth,
            outlineStyle: outlineStyle,
            boxShadow: boxShadow || 'none',
            hasFocusRing: hasRing,
            inViewport: inViewport,
            notCovered: notCovered,
            rect: {
                top: rect.top,
                bottom: rect.bottom,
                left: rect.left,
                right: rect.right,
                width: rect.width,
                height: rect.height
            }
        };
    }"""
    )
