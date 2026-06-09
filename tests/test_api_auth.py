import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app
from app.middleware.auth import encrypt_api_key


def _auth_side_effect(request):
    request.state.user = {"user_id": "test"}
    return {"user_id": "test"}


@pytest.fixture
def client():
    mock_auth = AsyncMock(side_effect=_auth_side_effect)
    with patch("app.api.auth.authenticate", mock_auth):
        with patch("app.api.admin.authenticate", mock_auth):
            yield TestClient(app)


@pytest.fixture
def client_with_db():
    mock_auth = AsyncMock(side_effect=_auth_side_effect)
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("app.api.auth.authenticate", mock_auth):
        with patch("app.api.auth.get_db", return_value=mock_cm):
            yield TestClient(app)


def test_list_keys_empty(client_with_db):
    resp = client_with_db.get("/api/auth/keys")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_keys_returns_copyable_key(client, tmp_path):
    from app.db.sqlite import get_db, init_db, set_db_path
    import asyncio
    import hashlib

    db_path = tmp_path / "keys.db"
    set_db_path(str(db_path))
    asyncio.run(init_db())
    key = "lgw_copyable"
    key_hash = hashlib.sha256(key.encode()).hexdigest()

    async def seed():
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO api_keys
                (id, key_hash, key_encrypted, user_id, name, quota_monthly, rate_limit_rps, allowed_tiers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (key_hash[:16], key_hash, encrypt_api_key(key), "test", "copyable", 100, 10, "cheap"),
            )
            await db.commit()

    asyncio.run(seed())
    resp = client.get("/api/auth/keys")
    assert resp.status_code == 200
    assert resp.json()[0]["key"] == key
    set_db_path("gateway.db")


def test_list_models(client):
    resp = client.get("/api/models")
    assert resp.status_code == 200
    models = resp.json()
    first = next(iter(models.values()))
    assert "provider" in first


def test_metrics_endpoint(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200


def test_config_endpoint_sanitizes_provider_keys(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert "gateway" in data
    for provider in data["models"]["providers"].values():
        assert provider.get("api_keys") == []


def test_admin_page_available():
    resp = TestClient(app).get("/admin")
    assert resp.status_code == 200
    assert "LLM Gateway Admin" in resp.text


def test_root_redirects_to_login():
    client = TestClient(app)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/login"


def test_llm_gateway_admin_page_available():
    resp = TestClient(app).get("/llm_gateway_admin")
    assert resp.status_code == 200
    assert "LLM Gateway Admin" in resp.text


def test_favicon_available():
    resp = TestClient(app).get("/llm_gateway_admin/favicon.svg")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers["content-type"]


def test_usage_endpoint_returns_db_summary(client):
    resp = client.get("/api/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "summary" in data
    assert "total_tokens" in data["summary"]


def test_ready_endpoint(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] in {"ready", "degraded"}


def test_provider_health_endpoint(client):
    resp = client.get("/api/providers/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    provider = next(iter(data["providers"].values()))
    assert "configured_key_count" in provider
    assert "env_key_configured" in provider
