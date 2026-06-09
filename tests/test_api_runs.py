import asyncio

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.base import ChatResult
from app.db.sqlite import close_db, init_db, set_db_path
from app.main import app
from app.services.load_balancer import LoadBalancer, ModelInstance


@pytest.fixture
def client():
    with patch("app.api.runs.authenticate", new=AsyncMock(return_value={"user_id": "test"})):
        with patch("app.api.runs.check_rate_limit", new=AsyncMock()):
            yield TestClient(app)


@pytest.fixture(autouse=True)
def isolated_sqlite(tmp_path):
    asyncio.run(close_db())
    set_db_path(str(tmp_path / "gateway-test.db"))
    asyncio.run(init_db())
    yield
    asyncio.run(close_db())
    set_db_path("gateway.db")


@pytest.fixture
def setup_lb(monkeypatch):
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "gpt-4o-mini": ModelInstance(name="gpt-4o-mini", provider="openai", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)
    return lb


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_run_no_auth():
    """Test that unauthenticated requests to /api/runs return 401."""
    unpatched_client = TestClient(app)
    resp = unpatched_client.post("/api/runs", json={
        "messages": [{"role": "user", "content": "Hi"}]
    })
    assert resp.status_code == 401


def test_create_run_rejects_disallowed_tier(monkeypatch):
    def auth_side_effect(request):
        request.state.user = {
            "user_id": "intern",
            "key_id": "key-1",
            "quota_monthly": 0,
            "allowed_tiers": ["cheap"],
        }
        return request.state.user

    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "expensive-model": ModelInstance(
            name="expensive-model",
            provider="openai",
            tier="expensive",
        ),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    with patch("app.api.runs.authenticate", new=AsyncMock(side_effect=auth_side_effect)):
        with patch("app.api.runs.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                client = TestClient(app)
                resp = client.post("/api/runs", json={
                    "messages": [{"role": "user", "content": "deep analysis"}],
                    "model_tier": "expensive",
                })

    assert resp.status_code == 403
    assert lb._instances["expensive-model"].current_connections == 0


def test_create_run_rejects_exhausted_quota():
    def auth_side_effect(request):
        request.state.user = {
            "user_id": "tester",
            "key_id": "key-1",
            "quota_monthly": 100,
            "allowed_tiers": ["cheap", "expensive"],
        }
        return request.state.user

    with patch("app.api.runs.authenticate", new=AsyncMock(side_effect=auth_side_effect)):
        with patch("app.api.runs.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=100)):
                client = TestClient(app)
                resp = client.post("/api/runs", json={
                    "messages": [{"role": "user", "content": "Hi"}],
                })

    assert resp.status_code == 429


def test_create_run_retries_next_model_on_failure(monkeypatch):
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

    with patch("app.api.runs.authenticate", new=AsyncMock(side_effect=auth_side_effect)):
        with patch("app.api.runs.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.runs.get_adapter", side_effect=adapter_for):
                    client = TestClient(app)
                    resp = client.post("/api/runs", json={
                        "messages": [{"role": "user", "content": "Hi"}],
                        "model_tier": "cheap",
                    })

    assert resp.status_code == 200
    assert resp.json()["model"] == "cheap-b"
    assert resp.json()["content"] == "fallback ok"


def test_create_run_does_not_retry_when_direct_model_fails(monkeypatch):
    def auth_side_effect(request):
        request.state.user = {
            "user_id": "model-pin-app",
            "key_id": "key-1",
            "quota_monthly": 0,
            "allowed_tiers": ["cheap", "expensive"],
        }
        return request.state.user

    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="openai", tier="cheap"),
        "cheap-b": ModelInstance(name="cheap-b", provider="deepseek", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    failing_adapter = MagicMock()
    failing_adapter.chat = AsyncMock(side_effect=RuntimeError("direct provider failed"))
    fallback_adapter = MagicMock()
    fallback_adapter.chat = AsyncMock(return_value=ChatResult(content="should not happen"))

    def adapter_for(model_name):
        return fallback_adapter if model_name == "cheap-b" else failing_adapter

    with patch("app.api.runs.authenticate", new=AsyncMock(side_effect=auth_side_effect)):
        with patch("app.api.runs.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.runs.get_adapter", side_effect=adapter_for):
                    client = TestClient(app)
                    resp = client.post("/api/runs", json={
                        "messages": [{"role": "user", "content": "Hi"}],
                        "model": "cheap-a",
                    })

    assert resp.status_code == 502
    fallback_adapter.chat.assert_not_called()


def test_create_run_does_not_escalate_cheap_to_expensive_on_failure(monkeypatch):
    def auth_side_effect(request):
        request.state.user = {
            "user_id": "cost-controlled-app",
            "key_id": "key-1",
            "quota_monthly": 0,
            "allowed_tiers": ["cheap", "expensive"],
        }
        return request.state.user

    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="openai", tier="cheap"),
        "expensive-a": ModelInstance(name="expensive-a", provider="lingya", tier="expensive"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    failing_adapter = MagicMock()
    failing_adapter.chat = AsyncMock(side_effect=RuntimeError("cheap provider failed"))
    expensive_adapter = MagicMock()
    expensive_adapter.chat = AsyncMock(return_value=ChatResult(content="should not happen"))

    def adapter_for(model_name):
        return expensive_adapter if model_name == "expensive-a" else failing_adapter

    with patch("app.api.runs.authenticate", new=AsyncMock(side_effect=auth_side_effect)):
        with patch("app.api.runs.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.runs.get_adapter", side_effect=adapter_for):
                    client = TestClient(app)
                    resp = client.post("/api/runs", json={
                        "messages": [{"role": "user", "content": "Hi"}],
                        "model_tier": "cheap",
                    })

    assert resp.status_code == 502
    expensive_adapter.chat.assert_not_called()


def test_create_run_response_includes_route_metadata(monkeypatch):
    def auth_side_effect(request):
        request.state.user = {
            "user_id": "route-app",
            "key_id": "key-route",
            "quota_monthly": 0,
            "allowed_tiers": ["cheap", "expensive"],
        }
        return request.state.user

    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "cheap-a": ModelInstance(name="cheap-a", provider="openai", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)

    adapter = MagicMock()
    adapter.chat = AsyncMock(return_value=ChatResult(
        content="ok",
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
        model="cheap-a",
    ))

    with patch("app.api.runs.authenticate", new=AsyncMock(side_effect=auth_side_effect)):
        with patch("app.api.runs.check_rate_limit", new=AsyncMock()):
            with patch("app.api.runs.get_monthly_usage", new=AsyncMock(return_value=0)):
                with patch("app.api.runs.get_adapter", return_value=adapter):
                    client = TestClient(app)
                    resp = client.post("/api/runs", json={
                        "messages": [{"role": "user", "content": "Hi"}],
                        "model_tier": "cheap",
                    })

    data = resp.json()
    assert resp.status_code == 200
    assert data["route"]["requested_tier"] == "cheap"
    assert data["route"]["resolved_tier"] == "cheap"
    assert data["route"]["attempted_models"] == ["cheap-a"]
    assert data["route"]["fallback_used"] is False
    assert data["route"]["cache_hit"] is False
