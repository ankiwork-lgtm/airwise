"""T3.6: app.css / app.js are served from explicit routes, with security headers."""

import logging

import pytest
from fastapi.testclient import TestClient

import airwise.main as main_module
from airwise.main import create_app
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


def test_index_repeated_requests_return_identical_bodies(client):
    first = client.get("/")
    second = client.get("/")
    for r in (first, second):
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/html; charset=utf-8"
        assert r.text == HTML
        _assert_headers(r)
    assert first.content == second.content


def test_index_is_served_from_disk_not_cached_in_memory(client, monkeypatch, tmp_path):
    """Editing index.html is reflected on the next request (no stale page under --reload)."""
    page = tmp_path / "index.html"
    monkeypatch.setattr(main_module, "INDEX_PATH", page)
    page.write_text("<p>one</p>", encoding="utf-8")
    assert client.get("/").text == "<p>one</p>"
    page.write_text("<p>two</p>", encoding="utf-8")
    assert client.get("/").text == "<p>two</p>"


def test_index_missing_file_returns_generic_500_without_leaks(monkeypatch, tmp_path, caplog):
    missing = tmp_path / "gone" / "index.html"
    monkeypatch.setattr(main_module, "INDEX_PATH", missing)
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        r = c.get("/")
    assert r.status_code == 500
    assert r.json() == {
        "error": {"code": "server_error", "message": "Internal server error.", "fields": []}
    }
    for text in (r.text, str(dict(r.headers))):
        assert str(missing) not in text
        assert "gone" not in text
        assert "FileNotFoundError" not in text
        assert "RuntimeError" not in text
        assert "does not exist" not in text
    _assert_headers(r)
    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    assert str(missing) not in logged


def test_app_js_content_sanity():
    assert JS.strip()
    assert '"use strict"' in JS
    assert "window.AirWise" in JS
    assert "<script" not in JS.lower()


def test_favicon_is_an_empty_204_with_cache_header_and_security_headers(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 204
    assert r.content == b""
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert "content-type" not in r.headers
    assert r.headers.get("content-length") in (None, "0")
    _assert_headers(r)


def test_favicon_is_not_in_the_openapi_schema(client):
    assert "/favicon.ico" not in client.get("/openapi.json").json()["paths"]
    assert "/favicon.ico" not in client.app.openapi()["paths"]


def test_favicon_does_not_touch_any_rate_limiter(monkeypatch):
    app = create_app()

    def forbidden(key):
        raise AssertionError(f"limiter used: {key}")

    for name in ("plan_limiter", "chat_limiter", "aqi_limiter"):
        monkeypatch.setattr(getattr(app.state, name), "check", forbidden)
    with TestClient(app) as c:
        for _ in range(100):
            assert c.get("/favicon.ico").status_code == 204


def test_favicon_head_request_does_not_error(client):
    assert client.head("/favicon.ico").status_code < 500
