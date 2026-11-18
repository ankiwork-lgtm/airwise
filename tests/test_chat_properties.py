"""Property tests for Chat_Service replies and scope guard."""
from __future__ import annotations

import asyncio
import os
import re
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st

from airwise.config import Deadline
from airwise.models import ChatRequest
from airwise.services.chat import (
    NOT_MEDICAL_ADVICE_NOTE,
    OFF_TOPIC_REPLY,
    SCOPE_DECLINE_REPLY,
    answer,
)
from tests.strategies import plans, profiles, readings


class StubLLM:
    def __init__(self, output: dict | None = None):
        self.output = output
        self.calls = 0

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        if self.output is None:
            raise AssertionError("LLM must not be called")
        return self.output


def _run(req: ChatRequest, llm: StubLLM):
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        return asyncio.run(answer(req, llm=llm, deadline=Deadline()))


@st.composite
def _requests(draw, message: st.SearchStrategy[str]) -> ChatRequest:
    return ChatRequest(
        message=draw(message),
        history=[],
        plan=draw(plans()),
        reading=draw(readings()),
        profile=draw(profiles()),
    )


_SAFE_MESSAGES = st.sampled_from(
    [
        "How is the air today?",
        "Should I keep the windows closed this evening?",
        "Why does the plan suggest a mask?",
        "What is PM2.5?",
    ]
)

_llm_replies = st.text(min_size=1, max_size=2000).filter(lambda s: s.strip() != "")


# Feature: airwise, Property 17: Health replies carry the not-medical-advice note
# **Validates: Requirements 8.4, 8.5**
@settings(max_examples=100, deadline=None)
@given(
    req=_requests(_SAFE_MESSAGES),
    reply=_llm_replies,
    on_topic=st.booleans(),
    discusses_health=st.booleans(),
)
def test_health_replies_carry_note_and_off_topic_is_declined(
    req, reply, on_topic, discusses_health
):
    llm = StubLLM({"reply": reply, "on_topic": on_topic, "discusses_health": discusses_health})
    result = _run(req, llm)
    assert llm.calls == 1
    assert not result.failed
    if not on_topic:
        assert result.reply == OFF_TOPIC_REPLY
        assert reply not in result.reply or reply in OFF_TOPIC_REPLY
        sentences = [s for s in re.split(r"[.!?]+", result.reply) if s.strip()]
        assert len(sentences) <= 2
    elif discusses_health:
        assert NOT_MEDICAL_ADVICE_NOTE in result.reply
        assert len(result.reply) <= 2000


# Feature: airwise, Property 18: Out-of-scope chat requests are declined without the LLM
# **Validates: Requirements 15.5**
_TRIGGERS = [
    "diagnose",
    "diagnosis",
    "do I have",
    "treatment",
    "cure",
    "medication",
    "medicine",
    "inhaler",
    "dosage",
    "declare GRAP",
    "officially confirm GRAP",
    "GRAP officially declared",
]
_case_fns = st.sampled_from([str.lower, str.upper, str.title, str.swapcase])
_surround = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=100
)


@st.composite
def _out_of_scope_messages(draw) -> str:
    phrase = draw(_case_fns)(draw(st.sampled_from(_TRIGGERS)))
    return f"{draw(_surround)} {phrase} {draw(_surround)}"


@settings(max_examples=100, deadline=None)
@given(req=_requests(_out_of_scope_messages()))
def test_out_of_scope_requests_are_declined_without_llm(req):
    llm = StubLLM(None)
    result = _run(req, llm)
    assert llm.calls == 0
    assert result.reply == SCOPE_DECLINE_REPLY
    assert not result.failed
