"""Chat route."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, Request

from airwise.config import Deadline
from airwise.models import ChatReply, ChatRequest
from airwise.routes.limits import LimitCheck
from airwise.services.chat import answer as chat_answer
from airwise.services.llm import LLMClient


def register_routes(
    app: FastAPI,
    get_llm_client: Callable[[], LLMClient],
    get_deadline: Callable[[], Deadline],
    limit_check: LimitCheck,
) -> None:
    """Register the route; the dependency functions stay in ``main`` so tests can override them."""

    @app.post("/api/chat", response_model=ChatReply)
    async def post_chat(
        body: ChatRequest,
        request: Request,
        llm: LLMClient = Depends(get_llm_client),
        deadline: Deadline = Depends(get_deadline),
    ) -> ChatReply:
        """Answer a chat message about the current plan."""
        limit_check(request)
        return await chat_answer(body, llm=llm, deadline=deadline)
