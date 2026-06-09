import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt
from unittest.mock import AsyncMock, patch

from app.middleware.auth import (
    authenticate,
    create_api_key,
    decrypt_api_key,
    encrypt_api_key,
    verify_api_key,
    verify_jwt,
)


@pytest.fixture
def app():
    app = FastAPI()

    @app.get("/protected")
    async def protected(request: Request):
        await authenticate(request)
        return {"user": request.state.user}

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_missing_auth_header(client):
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_invalid_api_key(client, monkeypatch):
    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("app.middleware.auth.get_db", return_value=mock_cm):
        resp = client.get("/protected", headers={"Authorization": "Bearer invalid-key"})
    assert resp.status_code == 401


def test_verify_jwt_valid(monkeypatch):
    monkeypatch.setenv("GATEWAY_JWT_SECRET", "test-secret-123")
    token = jwt.encode({"sub": "user-1", "role": "admin"}, "test-secret-123", algorithm="HS256")
    result = verify_jwt(token)
    assert result is not None
    assert result["user_id"] == "user-1"


def test_verify_jwt_invalid(monkeypatch):
    monkeypatch.setenv("GATEWAY_JWT_SECRET", "test-secret-123")
    result = verify_jwt("garbage.token.here")
    assert result is None


def test_verify_api_key_not_found(monkeypatch):
    import os
    import tempfile
    from app.db.sqlite import init_db, set_db_path
    fd, path = tempfile.mkstemp()
    os.close(fd)
    monkeypatch.setenv("SQLITE_DB_PATH", path)
    set_db_path(path)
    import asyncio
    asyncio.run(init_db())
    result = asyncio.run(verify_api_key("nonexistent_hash"))
    assert result is None
    os.unlink(path)


@pytest.mark.asyncio
async def test_create_api_key(monkeypatch):
    monkeypatch.setenv("SQLITE_DB_PATH", ":memory:")
    from app.db.sqlite import init_db, set_db_path
    import os
    import tempfile
    fd, path = tempfile.mkstemp()
    os.close(fd)
    set_db_path(path)
    await init_db()
    result = await create_api_key(name="test-key", user_id="user-1")
    assert result["key"].startswith("lgw_")
    assert result["name"] == "test-key"
    os.unlink(path)


def test_api_key_encryption_roundtrip(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY_ENCRYPTION_SECRET", "unit-test-secret")
    encrypted = encrypt_api_key("lgw_secret")
    assert encrypted != "lgw_secret"
    assert decrypt_api_key(encrypted) == "lgw_secret"


@pytest.mark.asyncio
async def test_create_api_key_with_allowed_tiers(monkeypatch):
    from app.db.sqlite import get_db, init_db, set_db_path
    import tempfile
    import os

    fd, path = tempfile.mkstemp()
    os.close(fd)
    set_db_path(path)
    await init_db()

    result = await create_api_key(
        name="intern-key",
        user_id="user-1",
        quota=1000,
        rate_limit=3,
        allowed_tiers=["cheap"],
    )

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT allowed_tiers FROM api_keys WHERE id = ?",
            (result["id"],),
        )
        row = await cursor.fetchone()

    assert row["allowed_tiers"] == "cheap"
    os.unlink(path)
