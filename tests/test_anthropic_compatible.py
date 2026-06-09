import asyncio

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.base import ChatResult
from app.db.sqlite import close_db, init_db, set_db_path
from app.main import app
from app.services.load_balancer import LoadBalancer, ModelInstance


@pytest.fixture(autouse=True)
def isolated_sqlite(tmp_path):
    asyncio.run(close_db())
    set_db_path(str(tmp_path / "gateway-test.db"))
    asyncio.run(init_db())
    yield
    asyncio.run(close_db())
    set_db_path("gateway.db")


@pytest.fixture
def client():
    with patch("app.api.anthropic_compatible.authenticate", new=AsyncMock(return_value={"user_id": "test"})):
        with patch("app.api.anthropic_compatible.check_rate_limit", new=AsyncMock()):
            yield TestClient(app)


def _auth_side_effect(request):
    request.state.user = {
        "user_id": "test",
        "key_id": "key-1",
        "quota_monthly": 0,
        "allowed_tiers": ["cheap", "expensive"],
    }
    return request.state.user


def test_messages_no_auth():
    unpatched = TestClient(app)
    resp = unpatched.post("/v1/anthropic", json={
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 1024,
    })
    assert resp.status_code == 401


def test_messages_non_stream_success(monkeypatch):
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="anthropic", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    adapter = MagicMock()
    adapter.chat = AsyncMock(return_value=ChatResult(
        content="Hello from Anthropic-compatible endpoint",
        prompt_tokens=5,
        completion_tokens=7,
        total_tokens=12,
        model="cheap-a",
        finish_reason="end_turn",
    ))

    with patch("app.api.anthropic_compatible.authenticate", new=AsyncMock(side_effect=_auth_side_effect)):
        with patch("app.api.anthropic_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.anthropic_compatible.get_adapter", return_value=adapter):
                    client = TestClient(app)
                    resp = client.post("/v1/anthropic", json={
                        "model": "cheap-a",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 1024,
                        "stream": False,
                    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["model"] == "cheap-a"
    assert data["content"][0]["type"] == "text"
    assert data["content"][0]["text"] == "Hello from Anthropic-compatible endpoint"
    assert data["stop_reason"] == "end_turn"
    assert data["usage"]["input_tokens"] == 5
    assert data["usage"]["output_tokens"] == 7


def test_messages_system_prompt_extracted(monkeypatch):
    """Anthropic 'system' field should be converted to an internal system message."""
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="anthropic", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    adapter = MagicMock()
    adapter.chat = AsyncMock(return_value=ChatResult(
        content="ok",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
    ))

    with patch("app.api.anthropic_compatible.authenticate", new=AsyncMock(side_effect=_auth_side_effect)):
        with patch("app.api.anthropic_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.anthropic_compatible.get_adapter", return_value=adapter):
                    client = TestClient(app)
                    resp = client.post("/v1/anthropic", json={
                        "model": "cheap-a",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "system": "You are a test assistant",
                        "max_tokens": 1024,
                    })

    assert resp.status_code == 200
    call_args = adapter.chat.call_args
    messages = call_args.kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are a test assistant"
    assert messages[1]["role"] == "user"


def test_messages_streaming_format(monkeypatch):
    """Streaming should yield Anthropic-compatible SSE events."""
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="anthropic", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    from app.adapters.base import ChatChunk

    async def fake_stream():
        yield ChatChunk(content="Hello ")
        yield ChatChunk(content="world")
        yield ChatChunk(content="", finish_reason="end_turn")

    adapter = MagicMock()
    adapter.chat = MagicMock(return_value=fake_stream())

    with patch("app.api.anthropic_compatible.authenticate", new=AsyncMock(side_effect=_auth_side_effect)):
        with patch("app.api.anthropic_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.anthropic_compatible.get_adapter", return_value=adapter):
                    client = TestClient(app)
                    resp = client.post("/v1/anthropic", json={
                        "model": "cheap-a",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 1024,
                        "stream": True,
                    })

    assert resp.status_code == 200
    lines = resp.text.strip().split("\n")
    events = {}
    for line in lines:
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            import json
            payload = json.loads(line[6:].strip())
            events[current_event] = payload

    assert "message_start" in events
    assert events["message_start"]["type"] == "message_start"
    assert events["message_start"]["message"]["role"] == "assistant"

    assert "content_block_delta" in events
    assert events["content_block_delta"]["delta"]["type"] == "text_delta"

    assert "message_delta" in events
    assert events["message_delta"]["delta"]["stop_reason"] == "end_turn"

    assert "message_stop" in events


def test_messages_omitted_model_uses_routing(monkeypatch):
    """When 'model' is omitted, the gateway should auto-route."""
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="anthropic", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    adapter = MagicMock()
    adapter.chat = AsyncMock(return_value=ChatResult(
        content="routed",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
    ))

    with patch("app.api.anthropic_compatible.authenticate", new=AsyncMock(side_effect=_auth_side_effect)):
        with patch("app.api.anthropic_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.anthropic_compatible.get_adapter", return_value=adapter):
                    client = TestClient(app)
                    resp = client.post("/v1/anthropic", json={
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 1024,
                    })

    assert resp.status_code == 200
    assert resp.json()["model"] == "cheap-a"


def test_messages_rejects_disallowed_tier(monkeypatch):
    def restricted_auth(request):
        request.state.user = {
            "user_id": "intern",
            "key_id": "key-1",
            "quota_monthly": 0,
            "allowed_tiers": ["cheap"],
        }
        return request.state.user

    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "expensive-a": ModelInstance(name="expensive-a", provider="anthropic", tier="expensive"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    with patch("app.api.anthropic_compatible.authenticate", new=AsyncMock(side_effect=restricted_auth)):
        with patch("app.api.anthropic_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                client = TestClient(app)
                resp = client.post("/v1/anthropic", json={
                    "model": "expensive-a",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1024,
                })

    assert resp.status_code == 403


def test_messages_fallback_on_failure(monkeypatch):
    def auth_side_effect(request):
        request.state.user = {
            "user_id": "critical-app",
            "key_id": "key-1",
            "quota_monthly": 0,
            "allowed_tiers": ["cheap", "expensive"],
        }
        return request.state.user

    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="anthropic", tier="cheap"),
        "cheap-b": ModelInstance(name="cheap-b", provider="anthropic", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    failing_adapter = MagicMock()
    failing_adapter.chat = AsyncMock(side_effect=RuntimeError("provider limited"))
    working_adapter = MagicMock()
    working_adapter.chat = AsyncMock(return_value=ChatResult(
        content="fallback ok",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        model="cheap-b",
        finish_reason="end_turn",
    ))

    def adapter_for(model_name):
        return failing_adapter if model_name == "cheap-a" else working_adapter

    with patch("app.api.anthropic_compatible.authenticate", new=AsyncMock(side_effect=auth_side_effect)):
        with patch("app.api.anthropic_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.anthropic_compatible.get_adapter", side_effect=adapter_for):
                    client = TestClient(app)
                    resp = client.post("/v1/anthropic", json={
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 1024,
                        "model_tier": "cheap",
                    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "cheap-b"
    assert data["content"][0]["text"] == "fallback ok"
