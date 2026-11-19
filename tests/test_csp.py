"""T3.7: strict Content-Security-Policy, tied to what the frontend really loads."""

import json
import re
from pathlib import Path

import pytest

from airwise.middleware import CONTENT_SECURITY_POLICY, SECURITY_HEADERS
from tests.frontend import CSS, HTML, JS
from tests.test_security_headers import _boom_client

VERCEL = json.loads((Path(__file__).resolve().parent.parent / "vercel.json").read_text("utf-8"))


def _csp(response) -> str:
    values = response.headers.get_list("content-security-policy")
    assert len(values) == 1, values
    return values[0]


def _directives(policy: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for part in policy.split(";"):
        tokens = part.split()
        if not tokens:
            continue
        name, sources = tokens[0], tokens[1:]
        assert name not in parsed, f"duplicate directive {name}"
        parsed[name] = sources
    return parsed


@pytest.mark.parametrize("path", ["/", "/app.js", "/app.css", "/api/health", "/no/such/path"])
def test_csp_on_responses(client, path):
    assert _csp(client.get(path)) == CONTENT_SECURITY_POLICY


def test_csp_on_500_from_generic_handler():
    with _boom_client() as c:
        r = c.get("/api/aqi", params={"city": "Delhi"})
    assert r.status_code == 500
    assert _csp(r) == CONTENT_SECURITY_POLICY


def test_policy_directives_are_strict():
    d = _directives(CONTENT_SECURITY_POLICY)
    assert d["default-src"] == ["'self'"]
    assert d["script-src"] == ["'self'"]
    assert d["style-src"] == ["'self'"]
    assert d["connect-src"] == ["'self'"]
    assert d["img-src"] == ["'self'"]
    assert d["form-action"] == ["'self'"]
    assert d["object-src"] == ["'none'"]
    assert d["base-uri"] == ["'none'"]
    assert d["frame-ancestors"] == ["'none'"]


def test_policy_has_no_weakening_tokens():
    tokens = [t for sources in _directives(CONTENT_SECURITY_POLICY).values() for t in sources]
    for token in tokens:
        assert token in {"'self'", "'none'"}, token
    for bad in ("'unsafe-inline'", "'unsafe-eval'", "*", "http:", "https:", "data:", "blob:"):
        assert bad not in tokens, bad
    assert "unsafe" not in CONTENT_SECURITY_POLICY
    assert "*" not in CONTENT_SECURITY_POLICY


def test_vercel_csp_equals_middleware_csp():
    rules = [r for r in VERCEL["headers"] if r["source"] == "/(.*)"]
    assert len(rules) == 1
    values = [
        h["value"] for h in rules[0]["headers"] if h["key"].lower() == "content-security-policy"
    ]
    assert values == [CONTENT_SECURITY_POLICY], (
        "vercel.json Content-Security-Policy must equal airwise.middleware.CONTENT_SECURITY_POLICY"
    )
    assert (b"Content-Security-Policy", CONTENT_SECURITY_POLICY.encode("ascii")) in SECURITY_HEADERS


# --- the policy must match what the frontend actually does ---------------------------------


def test_html_has_nothing_the_policy_would_block():
    assert not re.search(r"<script\b(?![^>]*\bsrc=)[^>]*>", HTML, re.I), "inline script"
    assert not re.search(r"<style\b|\sstyle\s*=|\son[a-z]+\s*=|javascript:", HTML, re.I)
    # No images, frames, plugins or <base>: img-src/object-src/base-uri stay locked down.
    assert not re.search(r"<(img|iframe|frame|object|embed|base|svg)\b", HTML, re.I)
    # The forms are handled by JS; a native submit could only go to our own origin anyway.
    assert not re.search(r"\saction\s*=\s*[\"']?(https?:)?//", HTML, re.I)


def test_css_loads_no_resources():
    # No url(), @import or @font-face: nothing for img-src/style-src/default-src to fetch.
    assert not re.search(r"url\(|@import|@font-face", CSS, re.I)


def test_js_uses_no_string_code_or_other_network_apis():
    forbidden = (
        r"\beval\s*\(",
        r"\bnew\s+Function\b",
        r"\bsetTimeout\s*\(\s*[\"'`]",
        r"\bsetInterval\s*\(\s*[\"'`]",
        r"\bdocument\s*\.\s*write",
        r"createElement\s*\(\s*[\"'](script|style|iframe|img)",
        r"\binsertRule\b",
        r"\bcssText\b",
        r"setAttribute\s*\(\s*[\"']style",
        r"\bXMLHttpRequest\b",
        r"\bWebSocket\b",
        r"\bEventSource\b",
        r"sendBeacon",
        r"\bnew\s+Image\b",
        r"\bimport\s*\(",
        r"\bimportScripts\b",
        r"\bnew\s+(Shared)?Worker\b",
    )
    for pattern in forbidden:
        assert not re.search(pattern, JS), pattern


def test_js_has_no_absolute_url_literals():
    assert not re.search(r"https?://|(?<![\w:])//[a-z0-9.-]+\.[a-z]{2,}", JS, re.I)


def test_js_network_calls_only_target_same_origin_api():
    # Exactly one fetch(), inside callApi(path, ...); every callApi target is a /api/ literal.
    assert len(re.findall(r"\bfetch\s*\(", JS)) == 1
    assert re.search(r"function callApi\(path, options\)\s*\{\s*return fetch\(path, options\)", JS)

    calls = re.findall(r"\bcallApi\(\s*(\"[^\"]*\"|\w+)", JS)
    targets = [c for c in calls if c != "path"]  # drop the function definition itself
    assert targets
    for target in targets:
        if target.startswith('"'):
            literal = target.strip('"')
        else:  # variable: it must be assigned from a "/api/..." literal
            m = re.search(rf"\b{re.escape(target)}\s*=\s*\"([^\"]*)\"", JS)
            assert m, f"cannot resolve callApi target {target}"
            literal = m.group(1)
        assert literal.startswith("/api/"), literal
