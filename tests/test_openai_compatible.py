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
    with patch("app.api.openai_compatible.authenticate", new=AsyncMock(return_value={"user_id": "test"})):
        with patch("app.api.openai_compatible.check_rate_limit", new=AsyncMock()):
            yield TestClient(app)


def _auth_side_effect(request):
    request.state.user = {
        "user_id": "test",
        "key_id": "key-1",
        "quota_monthly": 0,
        "allowed_tiers": ["cheap", "expensive"],
    }
    return request.state.user


def test_list_models_requires_auth():
    unpatched = TestClient(app)
    resp = unpatched.get("/v1/models")
    assert resp.status_code == 401


def test_list_models_returns_openai_format(client):
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)
    if data["data"]:
        first = data["data"][0]
        assert first["object"] == "model"
        assert "id" in first
        assert "owned_by" in first


def test_chat_completions_no_auth():
    unpatched = TestClient(app)
    resp = unpatched.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "Hi"}]
    })
    assert resp.status_code == 401


def test_chat_completions_non_stream_success(monkeypatch):
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="openai", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    adapter = MagicMock()
    adapter.chat = AsyncMock(return_value=ChatResult(
        content="Hello from OpenAI-compatible endpoint",
        prompt_tokens=5,
        completion_tokens=7,
        total_tokens=12,
        model="cheap-a",
        finish_reason="stop",
    ))

    with patch("app.api.openai_compatible.authenticate", new=AsyncMock(side_effect=_auth_side_effect)):
        with patch("app.api.openai_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.openai_compatible.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.openai_compatible.get_adapter", return_value=adapter):
                    client = TestClient(app)
                    resp = client.post("/v1/chat/completions", json={
                        "model": "cheap-a",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "stream": False,
                    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == "cheap-a"
    assert "chatcmpl-" in data["id"]
    assert "created" in data
    assert len(data["choices"]) == 1
    choice = data["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == "Hello from OpenAI-compatible endpoint"
    assert choice["finish_reason"] == "stop"
    assert data["usage"]["prompt_tokens"] == 5
    assert data["usage"]["completion_tokens"] == 7
    assert data["usage"]["total_tokens"] == 12


def test_chat_completions_omitted_model_uses_routing(monkeypatch):
    """When 'model' is omitted, the gateway should auto-route via resolve_route."""
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="openai", tier="cheap"),
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

    with patch("app.api.openai_compatible.authenticate", new=AsyncMock(side_effect=_auth_side_effect)):
        with patch("app.api.openai_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.openai_compatible.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.openai_compatible.get_adapter", return_value=adapter):
                    client = TestClient(app)
                    resp = client.post("/v1/chat/completions", json={
                        "messages": [{"role": "user", "content": "Hi"}],
                    })

    assert resp.status_code == 200
    assert resp.json()["model"] == "cheap-a"


def test_chat_completions_streaming_format(monkeypatch):
    """Streaming should yield OpenAI-compatible SSE chunks."""
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="openai", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    from app.adapters.base import ChatChunk

    async def fake_stream():
        yield ChatChunk(content="Hello ")
        yield ChatChunk(content="world")
        yield ChatChunk(content="", finish_reason="stop")

    adapter = MagicMock()
    adapter.chat = MagicMock(return_value=fake_stream())

    with patch("app.api.openai_compatible.authenticate", new=AsyncMock(side_effect=_auth_side_effect)):
        with patch("app.api.openai_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.openai_compatible.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.openai_compatible.get_adapter", return_value=adapter):
                    client = TestClient(app)
                    resp = client.post("/v1/chat/completions", json={
                        "model": "cheap-a",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "stream": True,
                    })

    assert resp.status_code == 200
    lines = [line for line in resp.text.split("\n") if line.startswith("data:")]
    # Should have role chunk, two content chunks, finish chunk, [DONE]
    assert len(lines) >= 4

    # Verify JSON structure of first real content chunk
    content_chunks = [l for l in lines if l != "data: [DONE]"]
    import json
    first = json.loads(content_chunks[0][5:].strip())
    assert first["object"] == "chat.completion.chunk"
    assert first["choices"][0]["delta"].get("role") == "assistant"

    second = json.loads(content_chunks[1][5:].strip())
    assert "content" in second["choices"][0]["delta"]


def test_chat_completions_rejects_exhausted_quota():
    def quota_auth(request):
        request.state.user = {
            "user_id": "tester",
            "key_id": "key-1",
            "quota_monthly": 100,
            "allowed_tiers": ["cheap", "expensive"],
        }
        return request.state.user

    with patch("app.api.openai_compatible.authenticate", new=AsyncMock(side_effect=quota_auth)):
        with patch("app.api.openai_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=100)):
                client = TestClient(app)
                resp = client.post("/v1/chat/completions", json={
                    "messages": [{"role": "user", "content": "Hi"}],
                })

    assert resp.status_code == 429


def test_chat_completions_rejects_disallowed_tier(monkeypatch):
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
        "expensive-a": ModelInstance(name="expensive-a", provider="openai", tier="expensive"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    with patch("app.api.openai_compatible.authenticate", new=AsyncMock(side_effect=restricted_auth)):
        with patch("app.api.openai_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.openai_compatible.get_monthly_usage", new=AsyncMock(return_value=0)):
                client = TestClient(app)
                resp = client.post("/v1/chat/completions", json={
                    "model": "expensive-a",
                    "messages": [{"role": "user", "content": "Hi"}],
                })

    assert resp.status_code == 403


def test_chat_completions_fallback_on_failure(monkeypatch):
    """If the first model fails, the gateway should try the next one."""
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
        "cheap-a": ModelInstance(name="cheap-a", provider="openai", tier="cheap"),
        "cheap-b": ModelInstance(name="cheap-b", provider="openai", tier="cheap"),
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
    ))

    def adapter_for(model_name):
        return failing_adapter if model_name == "cheap-a" else working_adapter

    with patch("app.api.openai_compatible.authenticate", new=AsyncMock(side_effect=auth_side_effect)):
        with patch("app.api.openai_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.openai_compatible.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.openai_compatible.get_adapter", side_effect=adapter_for):
                    client = TestClient(app)
                    resp = client.post("/v1/chat/completions", json={
                        "messages": [{"role": "user", "content": "Hi"}],
                        "model_tier": "cheap",
                    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "cheap-b"
    assert data["choices"][0]["message"]["content"] == "fallback ok"


def test_chat_completions_temperature_and_max_tokens_passed_through(monkeypatch):
    """Verify that temperature and max_tokens are forwarded to the adapter."""
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="openai", tier="cheap"),
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

    with patch("app.api.openai_compatible.authenticate", new=AsyncMock(side_effect=_auth_side_effect)):
        with patch("app.api.openai_compatible.check_rate_limit", new=AsyncMock()):
            with patch("app.api.openai_compatible.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.openai_compatible.get_adapter", return_value=adapter):
                    client = TestClient(app)
                    resp = client.post("/v1/chat/completions", json={
                        "model": "cheap-a",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "temperature": 0.5,
                        "max_tokens": 256,
                    })

    assert resp.status_code == 200
    call_kwargs = adapter.chat.call_args.kwargs
    assert call_kwargs["temperature"] == 0.5
    assert call_kwargs["max_tokens"] == 256
