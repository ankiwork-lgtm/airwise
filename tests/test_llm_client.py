"""AnthropicClient request construction and model default (Requirement 6.10)."""

import asyncio
import json

import httpx
import pytest

from airwise.config import DEFAULT_LLM_MODEL, anthropic_base_url, llm_model
from airwise.services import llm
from airwise.services.llm import AnthropicClient, LLMUnavailable

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def _install_fake(monkeypatch, response=None):
    calls = {}

    def handler(request):
        calls["url"] = str(request.url)
        calls["headers"] = request.headers
        calls["body"] = json.loads(request.content)
        if response is not None:
            return response
        return httpx.Response(
            200, json={"content": [{"type": "tool_use", "name": "plan", "input": {"a": 1}}]}
        )

    monkeypatch.setattr(llm, "_TRANSPORT", httpx.MockTransport(handler))
    return calls


def _run(timeout_s=7.5):
    return asyncio.run(
        AnthropicClient().complete_json(
            system="sys", user="usr", schema_name="plan", schema=SCHEMA, timeout_s=timeout_s
        )
    )


def test_request_construction(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example/v1/")
    monkeypatch.setenv("LLM_MODEL", "my-model")
    calls = _install_fake(monkeypatch)
    assert _run() == {"a": 1}
    assert calls["url"] == "https://gw.example/v1/messages"
    assert calls["headers"]["x-api-key"] == "sk-test"
    assert "anthropic-version" in calls["headers"]
    b = calls["body"]
    assert b["model"] == "my-model"
    assert b["system"] == "sys"
    assert b["messages"] == [{"role": "user", "content": "usr"}]
    assert b["tools"] == [
        {
            "name": "plan",
            "description": "Return the answer as structured JSON.",
            "input_schema": SCHEMA,
        }
    ]
    assert b["tool_choice"] == {"type": "tool", "name": "plan"}


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls = _install_fake(monkeypatch)
    with pytest.raises(LLMUnavailable):
        _run()
    assert calls == {}


def test_no_tool_use_block_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _install_fake(
        monkeypatch, httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}]})
    )
    with pytest.raises(LLMUnavailable):
        _run()


def test_http_error_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _install_fake(monkeypatch, httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(LLMUnavailable):
        _run()


def test_model_default_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert llm_model() == DEFAULT_LLM_MODEL == "claude-haiku-5-5"


@pytest.mark.parametrize("value", ["", "   "])
def test_model_default_when_empty(monkeypatch, value):
    monkeypatch.setenv("LLM_MODEL", value)
    assert llm_model() == DEFAULT_LLM_MODEL


def test_base_url_default_and_trailing_slash(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert anthropic_base_url() == "https://api.anthropic.com/v1"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example/v1/")
    assert anthropic_base_url() == "https://gw.example/v1"


def test_default_model_sent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    calls = _install_fake(monkeypatch)
    _run()
    assert calls["body"]["model"] == "claude-haiku-5-5"


# --- T4.1: one shared httpx.AsyncClient ---------------------------------------------------


def _ok_response():
    return httpx.Response(
        200, json={"content": [{"type": "tool_use", "name": "plan", "input": {"a": 1}}]}
    )


def test_two_calls_reuse_one_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _install_fake(monkeypatch)
    built = []
    real = httpx.AsyncClient

    def counting(*args, **kwargs):
        built.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(llm.httpx, "AsyncClient", counting)

    async def go():
        c = AnthropicClient()
        kw = {"system": "s", "user": "u", "schema_name": "plan", "schema": SCHEMA}
        await c.complete_json(timeout_s=5, **kw)
        first = llm._get_client()
        await c.complete_json(timeout_s=5, **kw)
        assert llm._get_client() is first
        assert not first.is_closed  # not closed between calls

    asyncio.run(go())
    assert len(built) == 1


def test_changed_transport_is_used(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    answered = []

    def make(name):
        def handler(request):
            answered.append(name)
            return _ok_response()

        return httpx.MockTransport(handler)

    async def go():
        c = AnthropicClient()
        kw = {"system": "s", "user": "u", "schema_name": "plan", "schema": SCHEMA, "timeout_s": 5}
        monkeypatch.setattr(llm, "_TRANSPORT", make("A"))
        await c.complete_json(**kw)
        monkeypatch.setattr(llm, "_TRANSPORT", make("B"))
        await c.complete_json(**kw)

    asyncio.run(go())
    assert answered == ["A", "B"]


def test_failure_does_not_poison_shared_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    responses = [httpx.Response(500, text="boom"), _ok_response()]
    monkeypatch.setattr(llm, "_TRANSPORT", httpx.MockTransport(lambda r: responses.pop(0)))
    seen = []

    async def go():
        c = AnthropicClient()
        kw = {"system": "s", "user": "u", "schema_name": "plan", "schema": SCHEMA, "timeout_s": 5}
        with pytest.raises(LLMUnavailable) as err:
            await c.complete_json(**kw)
        assert err.value.status_code == 500
        assert str(err.value) == "LLM call failed (HTTPStatusError 500): boom"
        seen.append(llm._get_client())
        assert await c.complete_json(**kw) == {"a": 1}
        assert llm._get_client() is seen[0]

    asyncio.run(go())


def test_timeout_does_not_poison_shared_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    delays = [0.3, 0.0]

    async def handler(request):
        await asyncio.sleep(delays.pop(0))
        return _ok_response()

    monkeypatch.setattr(llm, "_TRANSPORT", httpx.MockTransport(handler))

    async def go():
        c = AnthropicClient()
        kw = {"system": "s", "user": "u", "schema_name": "plan", "schema": SCHEMA}
        with pytest.raises(LLMUnavailable) as err:
            await c.complete_json(timeout_s=0.05, **kw)
        assert str(err.value) == "LLM call failed (TimeoutError)."
        assert await c.complete_json(timeout_s=5, **kw) == {"a": 1}

    asyncio.run(go())


def test_zero_timeout_fails_fast(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _install_fake(monkeypatch)
    with pytest.raises(LLMUnavailable) as err:
        _run(timeout_s=0.0)
    assert str(err.value) == "LLM call failed (TimeoutError)."


def test_each_asyncio_run_gets_a_client_valid_for_its_loop(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _install_fake(monkeypatch)
    clients = []

    async def go():
        result = await AnthropicClient().complete_json(
            system="s", user="u", schema_name="plan", schema=SCHEMA, timeout_s=5
        )
        clients.append(llm._get_client())
        return result

    for _ in range(3):  # three separate event loops
        assert asyncio.run(go()) == {"a": 1}
    assert len({id(c) for c in clients}) == 3
    assert all(not c.is_closed for c in clients)


def test_aclose_closes_and_clears_and_is_idempotent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _install_fake(monkeypatch)

    async def go():
        await llm.aclose_llm_client()  # nothing cached: no-op
        c = AnthropicClient()
        kw = {"system": "s", "user": "u", "schema_name": "plan", "schema": SCHEMA, "timeout_s": 5}
        await c.complete_json(**kw)
        first = llm._get_client()
        await llm.aclose_llm_client()
        assert first.is_closed
        assert llm.llm_client_cache.shared is None
        await llm.aclose_llm_client()  # second time: no-op
        assert await c.complete_json(**kw) == {"a": 1}
        second = llm._get_client()
        assert second is not first
        assert not second.is_closed

    asyncio.run(go())


def test_api_key_is_read_on_every_call(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.headers["x-api-key"])
        return _ok_response()

    monkeypatch.setattr(llm, "_TRANSPORT", httpx.MockTransport(handler))

    async def go():
        c = AnthropicClient()
        kw = {"system": "s", "user": "u", "schema_name": "plan", "schema": SCHEMA, "timeout_s": 5}
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-one")
        await c.complete_json(**kw)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-two")
        await c.complete_json(**kw)

    asyncio.run(go())
    assert seen == ["sk-one", "sk-two"]
