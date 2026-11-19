"""Error handling and secret hygiene: generic 500 body, fake key never leaks."""
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from airwise.main import create_app, get_http_client, get_llm_client
from airwise.services import llm as llm_module
from tests.test_aqi_endpoint import AQ_OK, GEO_OK, make_client, make_handler
from tests.test_plan_validation import VALID_PROFILE

FAKE_KEY = "sk-fake-SECRET-0123456789abcdef"
SECRET_PATH = r"C:\Users\secret\project\airwise\main.py"


def _boom_client() -> TestClient:
    app = create_app()

    async def boom():
        raise RuntimeError(f"kaboom {SECRET_PATH} key={FAKE_KEY}")

    app.dependency_overrides[get_http_client] = boom
    return TestClient(app, raise_server_exceptions=False)


def test_forced_exception_returns_generic_500_without_traceback_or_path(monkeypatch, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    caplog.set_level(logging.DEBUG)
    with _boom_client() as c:
        r = c.post("/api/plan", json={"profile": VALID_PROFILE})
    assert r.status_code == 500
    assert r.json() == {
        "error": {
            "code": "server_error",
            "message": "Internal server error.",
            "fields": [],
        }
    }
    for text in (r.text, str(dict(r.headers))):
        assert "Traceback" not in text
        assert "kaboom" not in text
        assert SECRET_PATH not in text
        assert "main.py" not in text
        assert FAKE_KEY not in text
    # Only the exception class name is logged.
    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "RuntimeError" in logged
    assert "kaboom" not in logged
    assert SECRET_PATH not in logged
    assert FAKE_KEY not in logged
    assert all(rec.exc_info is None for rec in caplog.records if rec.name == "airwise")


def _assert_no_secret(response, caplog):
    assert FAKE_KEY not in response.text
    for k, v in response.headers.items():
        assert FAKE_KEY not in k and FAKE_KEY not in v
    for rec in caplog.records:
        assert FAKE_KEY not in rec.getMessage()
        assert FAKE_KEY not in str(rec.__dict__.get("exc_text") or "")


def test_fake_key_not_in_responses_or_logs_on_success_paths(monkeypatch, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    caplog.set_level(logging.DEBUG)
    with make_client(make_handler(geocode=GEO_OK, aq=AQ_OK)) as c:
        for r in (
            c.get("/api/health"),
            c.get("/"),
            c.get("/api/aqi", params={"city": "Delhi"}),
            c.get("/api/aqi"),  # 422
            c.post("/api/plan", json={"profile": {}}),  # 422
        ):
            _assert_no_secret(r, caplog)


def test_fake_key_not_leaked_after_llm_failure(monkeypatch, caplog):
    """SDK raises an error whose text contains the key: plan falls back, chat reports failure."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    caplog.set_level(logging.DEBUG)

    def failing(request):
        raise RuntimeError(f"401 Incorrect API key provided: {FAKE_KEY}")

    monkeypatch.setattr(llm_module, "_TRANSPORT", httpx.MockTransport(failing))

    c = make_client(make_handler(geocode=GEO_OK, aq=AQ_OK))
    c.app.dependency_overrides[get_llm_client] = llm_module.AnthropicClient
    with c:
        plan_resp = c.post("/api/plan", json={"profile": VALID_PROFILE})
        assert plan_resp.status_code == 200
        body = plan_resp.json()
        assert body["plan"]["fallback"] is True
        _assert_no_secret(plan_resp, caplog)

        chat_resp = c.post(
            "/api/chat",
            json={
                "message": "How do I reduce exposure?",
                "history": [],
                "plan": body["plan"],
                "reading": body["reading"],
                "profile": VALID_PROFILE,
            },
        )
        assert chat_resp.status_code == 200
        assert chat_resp.json()["failed"] is True
        _assert_no_secret(chat_resp, caplog)


def test_llm_unavailable_message_has_no_key(monkeypatch):
    import asyncio

    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)

    def failing(request):
        raise RuntimeError(f"bad key {FAKE_KEY}")

    monkeypatch.setattr(llm_module, "_TRANSPORT", httpx.MockTransport(failing))

    with pytest.raises(llm_module.LLMUnavailable) as info:
        asyncio.run(
            llm_module.AnthropicClient().complete_json(
                system="s", user="u", schema_name="n", schema={}, timeout_s=2
            )
        )
    assert FAKE_KEY not in str(info.value)
    assert FAKE_KEY not in repr(info.value)
    assert info.value.__cause__ is None
