import asyncio

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.base import ChatResult
from app.db.sqlite import get_db, init_db, set_db_path
from app.main import app
from app.services.load_balancer import LoadBalancer, ModelInstance


def _auth_side_effect(request):
    request.state.user = {
        "user_id": "governance-user",
        "key_id": "governance-key",
        "quota_monthly": 0,
        "allowed_tiers": ["cheap", "expensive"],
    }
    return request.state.user


@pytest.fixture(autouse=True)
def isolated_sqlite(tmp_path):
    set_db_path(str(tmp_path / "governance.db"))
    asyncio.run(init_db())
    yield
    set_db_path("gateway.db")


@pytest.fixture
def admin_client():
    mock_auth = AsyncMock(side_effect=_auth_side_effect)
    with patch("app.api.auth.authenticate", mock_auth):
        with patch("app.api.admin.authenticate", mock_auth):
            with patch("app.api.runs.authenticate", mock_auth):
                with patch("app.api.runs.check_rate_limit", new=AsyncMock()):
                    yield TestClient(app)


@pytest.fixture
def setup_lb(monkeypatch):
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "deepseek-chat": ModelInstance(name="deepseek-chat", provider="deepseek", tier="cheap"),
    }
    lb._lock = pytest.importorskip("asyncio").Lock()
    monkeypatch.setattr("app.services.load_balancer._lb", lb)
    monkeypatch.setattr("app.services.load_balancer.get_load_balancer", lambda: lb)
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)
    return lb


def test_successful_run_persists_request_trace(admin_client, setup_lb):
    adapter = MagicMock()
    adapter.chat = AsyncMock(return_value=ChatResult(
        content="trace ok",
        prompt_tokens=8,
        completion_tokens=4,
        total_tokens=12,
        model="deepseek-chat",
    ))

    with patch("app.api.runs.get_adapter", return_value=adapter):
        resp = admin_client.post(
            "/api/runs",
            headers={"X-Request-ID": "req-test-1"},
            json={"messages": [{"role": "user", "content": "hello"}], "model_tier": "cheap"},
        )

    assert resp.status_code == 200
    traces = admin_client.get("/api/traces").json()
    assert traces["items"][0]["request_id"] == "req-test-1"
    assert traces["items"][0]["provider"] == "deepseek"
    assert traces["items"][0]["model_name"] == "deepseek-chat"
    assert traces["items"][0]["status"] == "success"
    assert traces["items"][0]["total_tokens"] == 12


def test_provider_sla_aggregates_success_and_failure(admin_client):
    async def seed():
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO request_traces
                (request_id, api_key_id, user_id, provider, model_name, tier, status, latency_ms, total_tokens)
                VALUES
                ('r1', 'k1', 'u1', 'deepseek', 'deepseek-chat', 'cheap', 'success', 100, 10),
                ('r2', 'k1', 'u1', 'deepseek', 'deepseek-chat', 'cheap', 'error', 300, 0),
                ('r3', 'k2', 'u2', 'kimi', 'kimi-k2.5', 'cheap', 'success', 200, 20)
                """
            )
            await db.commit()

    asyncio.run(seed())

    resp = admin_client.get("/api/providers/sla")
    assert resp.status_code == 200
    data = resp.json()["providers"]
    deepseek = next(item for item in data if item["provider"] == "deepseek")
    assert deepseek["total_requests"] == 2
    assert deepseek["success_rate"] == 0.5
    assert deepseek["error_count"] == 1
    assert deepseek["p95_latency_ms"] == 300


def test_policy_draft_is_saved_and_audited(admin_client):
    payload = {
        "name": "production-routing-v1",
        "content": {
            "rules": [{"name": "finance", "tier": "expensive"}],
            "providers": {"deepseek": {"max_concurrency": 80, "timeout_ms": 30000}},
        },
    }
    resp = admin_client.post("/api/policies/drafts", json=payload)

    assert resp.status_code == 200
    draft = resp.json()
    assert draft["name"] == "production-routing-v1"
    assert draft["status"] == "draft"

    policies = admin_client.get("/api/policies").json()
    assert policies["drafts"][0]["name"] == "production-routing-v1"

    audit = admin_client.get("/api/audit").json()
    assert audit["items"][0]["action"] == "policy.draft.create"
    assert audit["items"][0]["target_id"] == str(draft["id"])
