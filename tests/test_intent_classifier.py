import json
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest

from app.adapters.base import AdapterRegistry, ChatResult
from app.adapters.openai_adapter import OpenAIAdapter
from app.models.request import IntentResult
from app.services.intent_classifier import cache_intent, classify_intent, get_cached_intent


@pytest.fixture
def fake_redis_client():
    return fakeredis.FakeAsyncRedis()


@pytest.fixture(autouse=True)
def patch_redis(fake_redis_client, monkeypatch):
    async def mock_get():
        return fake_redis_client
    monkeypatch.setattr("app.services.intent_classifier.get_redis", mock_get)
    monkeypatch.setattr("app.db.redis.get_redis", mock_get)
    yield fake_redis_client


@pytest.fixture(autouse=True)
def register_openai_adapter(monkeypatch):
    AdapterRegistry.register("openai", OpenAIAdapter)
    yield
    AdapterRegistry._adapters.pop("openai", None)


def test_content_hash_consistent():
    from app.services.intent_classifier import _content_hash
    h1 = _content_hash([{"role": "user", "content": "hello"}])
    h2 = _content_hash([{"role": "user", "content": "hello"}])
    assert h1 == h2


@pytest.mark.asyncio
async def test_cache_roundtrip(fake_redis_client):
    intent = IntentResult(tier="cheap", task_type="query")
    messages = [{"role": "user", "content": "test cache"}]
    await cache_intent(messages, intent, ttl=60)
    cached = await get_cached_intent(messages)
    assert cached is not None
    assert cached.tier == "cheap"


@pytest.mark.asyncio
async def test_cache_miss():
    messages = [{"role": "user", "content": "nonexistent intent"}]
    result = await get_cached_intent(messages)
    assert result is None


@pytest.mark.asyncio
async def test_classify_timeout_falls_back(fake_redis_client):
    messages = [{"role": "user", "content": "some request for timeout test"}]
    with patch.object(OpenAIAdapter, "chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = TimeoutError("timeout")
        result = await classify_intent(messages)
        assert result.tier == "cheap"
        assert result.task_type == "unknown"


@pytest.mark.asyncio
async def test_classify_returns_expensive(fake_redis_client):
    messages = [{"role": "user", "content": "analyze this complex alert"}]
    with patch.object(OpenAIAdapter, "chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = ChatResult(
            content=json.dumps({"tier": "expensive", "task_type": "alert_analysis"}),
            total_tokens=20,
        )
        result = await classify_intent(messages)
        assert result.tier == "expensive"
        assert result.task_type == "alert_analysis"
