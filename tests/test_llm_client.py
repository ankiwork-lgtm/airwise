"""OpenAIClient argument construction and model default (Requirement 6.10)."""
import asyncio
from types import SimpleNamespace

import pytest

from airwise.config import DEFAULT_OPENAI_MODEL, openai_model
from airwise.services import llm
from airwise.services.llm import LLMUnavailable, OpenAIClient

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def _install_fake(monkeypatch, content='{"a": 1}'):
    calls = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            calls["create"] = kwargs
            msg = SimpleNamespace(content=content)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            calls["init"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm, "AsyncOpenAI", FakeAsyncOpenAI)
    return calls


def _run(timeout_s=7.5):
    return asyncio.run(
        OpenAIClient().complete_json(
            system="sys", user="usr", schema_name="plan", schema=SCHEMA, timeout_s=timeout_s
        )
    )


def test_argument_construction(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "my-model")
    calls = _install_fake(monkeypatch)
    assert _run() == {"a": 1}
    assert calls["init"] == {"api_key": "sk-test", "timeout": 7.5, "max_retries": 0}
    c = calls["create"]
    assert c["model"] == "my-model"
    assert c["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert c["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "plan", "strict": True, "schema": SCHEMA},
    }


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _install_fake(monkeypatch)
    with pytest.raises(LLMUnavailable):
        _run()


def test_bad_json_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _install_fake(monkeypatch, content="not json")
    with pytest.raises(LLMUnavailable):
        _run()


def test_model_default_when_unset(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert openai_model() == DEFAULT_OPENAI_MODEL == "gpt-4o-mini"


@pytest.mark.parametrize("value", ["", "   "])
def test_model_default_when_empty(monkeypatch, value):
    monkeypatch.setenv("OPENAI_MODEL", value)
    assert openai_model() == "gpt-4o-mini"


def test_default_model_passed_to_sdk(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    calls = _install_fake(monkeypatch)
    _run()
    assert calls["create"]["model"] == "gpt-4o-mini"
