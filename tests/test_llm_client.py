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
