import pytest

from app.models.request import ChatRequest, Message
from app.models.response import ChatResponse, UsageInfo
from app.services.result_cache import build_cache_key, get_cached_response, set_cached_response


@pytest.fixture
def fake_redis(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.data = {}

        async def get(self, key):
            return self.data.get(key)

        async def setex(self, key, ttl, value):
            self.data[key] = value

    redis = FakeRedis()

    async def _get_redis():
        return redis

    monkeypatch.setattr("app.services.result_cache.get_redis", _get_redis)
    return redis


@pytest.mark.asyncio
async def test_result_cache_roundtrip(fake_redis):
    request = ChatRequest(
        messages=[Message(role="user", content="cache me")],
        temperature=0,
        model_tier="cheap",
    )
    response = ChatResponse(
        id="run-1",
        model="deepseek-chat",
        tier="cheap",
        content="cached",
        usage=UsageInfo(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )

    key = build_cache_key(request, "cheap")
    await set_cached_response(key, response, ttl=60)
    cached = await get_cached_response(key)

    assert cached is not None
    assert cached.content == "cached"
    assert cached.usage.total_tokens == 3
