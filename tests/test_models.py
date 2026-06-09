import pytest
from pydantic import ValidationError

from app.models.request import ChatRequest, IntentResult, Message, ToolRef
from app.models.response import ChatResponse, ChunkResponse, ErrorResponse, UsageInfo


def test_chat_request_minimal():
    req = ChatRequest(messages=[Message(role="user", content="Hello")])
    assert req.stream is False
    assert req.model_tier == "auto"
    assert req.temperature == 0.7


def test_chat_request_full():
    req = ChatRequest(
        messages=[Message(role="user", content="Analyze this alert")],
        stream=True,
        model_tier="expensive",
        preferred_model="claude-opus",
        max_tokens=8192,
        tools=[ToolRef(name="execute_sql")],
    )
    assert req.stream is True
    assert len(req.tools) == 1


def test_chat_request_invalid_tier():
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[Message(role="user", content="Hi")],
            model_tier="invalid",
        )


def test_chat_request_invalid_temperature():
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[Message(role="user", content="Hi")],
            temperature=3.0,
        )


def test_chat_response():
    resp = ChatResponse(
        id="run-123",
        model="gpt-4o-mini",
        tier="cheap",
        content="Hello!",
        usage=UsageInfo(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    assert resp.usage.total_tokens == 15


def test_chunk_response():
    chunk = ChunkResponse(id="run-123", model="gpt-4o-mini", content="Hel")
    assert chunk.finish_reason is None
    assert chunk.usage is None


def test_intent_result_valid():
    intent = IntentResult(tier="cheap", task_type="query")
    assert intent.tier == "cheap"


def test_intent_result_invalid_tier():
    with pytest.raises(ValidationError):
        IntentResult(tier="auto", task_type="query")


def test_error_response():
    err = ErrorResponse(error="Not found", code="404", details="Resource missing")
    assert err.code == "404"
    assert err.details == "Resource missing"


def test_tool_ref():
    tool = ToolRef(name="execute_sql", description="Run SQL query")
    assert tool.name == "execute_sql"
    assert tool.parameters is None


def test_usage_info():
    usage = UsageInfo(prompt_tokens=10, completion_tokens=5)
    assert usage.total_tokens == 0  # not auto-computed by default


def test_max_tokens_zero_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(messages=[Message(role="user", content="Hi")], max_tokens=0)


def test_message_invalid_role():
    with pytest.raises(ValidationError):
        Message(role="hacker", content="Hi")


def test_temperature_boundaries():
    req_min = ChatRequest(messages=[Message(role="user", content="Hi")], temperature=0.0)
    req_max = ChatRequest(messages=[Message(role="user", content="Hi")], temperature=2.0)
    assert req_min.temperature == 0.0
    assert req_max.temperature == 2.0
