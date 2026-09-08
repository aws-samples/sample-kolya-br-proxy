"""Regression test: the OpenAI ``developer`` role is accepted and normalized.

OpenAI reasoning models (and clients such as pi routed through
``/v1/chat/completions``) send the newer ``developer`` role in place of
``system``. Bedrock has no ``developer`` role, so ``ChatMessage`` collapses it
to ``system`` before validation. Before the fix the ``role`` Literal rejected
it with a 422 ("Input should be 'system', 'user', 'assistant' or 'tool'").
"""

import pytest
from pydantic import ValidationError

from app.schemas.openai import ChatCompletionRequest, ChatMessage


def test_developer_role_normalized_to_system():
    assert ChatMessage(role="developer", content="you are helpful").role == "system"


def test_developer_role_in_full_request():
    req = ChatCompletionRequest(
        model="openai.gpt-5.6-sol",
        messages=[
            {"role": "developer", "content": "sys prompt"},
            {"role": "user", "content": "hi"},
        ],
    )
    assert [m.role for m in req.messages] == ["system", "user"]


def test_standard_roles_unchanged():
    for role in ("system", "user", "assistant", "tool"):
        assert ChatMessage(role=role, content="x").role == role


def test_unknown_role_still_rejected():
    with pytest.raises(ValidationError):
        ChatMessage(role="nope", content="x")
