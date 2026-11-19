"""T3.6: app.css / app.js are served from explicit routes, with security headers."""

import pytest

from tests.frontend import CSS, HTML, JS
from tests.test_security_headers import _assert_headers


def test_app_css_served(client):
    r = client.get("/app.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert r.text == CSS


def test_app_js_served(client):
    r = client.get("/app.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.text == JS


@pytest.mark.parametrize("path", ["/app.css", "/app.js"])
def test_asset_responses_carry_security_headers(client, path):
    _assert_headers(client.get(path))


@pytest.mark.parametrize(
    "path",
    [
        "/public/index.html",
        "/public/app.js",
        "/app.js/../airwise/main.py",
        "/static/..%2fairwise/main.py",
        "/airwise/main.py",
        "/index.html",
    ],
)
def test_no_other_files_are_exposed(client, path):
    r = client.get(path)
    assert 400 <= r.status_code < 500, path
    assert "create_app" not in r.text
    assert "AirWise" not in r.text


def test_index_references_assets(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert r.text == HTML
    assert 'href="/app.css"' in r.text
    assert 'src="/app.js"' in r.text


def test_app_js_content_sanity():
    assert JS.strip()
    assert '"use strict"' in JS
    assert "window.AirWise" in JS
    assert "<script" not in JS.lower()
