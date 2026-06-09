import hashlib

from app.db.redis import get_redis
from app.models.request import ChatRequest
from app.models.response import ChatResponse

RESULT_CACHE_PREFIX = "result:"


def should_cache_request(request: ChatRequest) -> bool:
    return not request.stream and request.temperature == 0


def build_cache_key(request: ChatRequest, tier: str) -> str:
    payload = request.model_dump_json(exclude={"stream"})
    digest = hashlib.sha256(f"{tier}:{payload}".encode()).hexdigest()
    return f"{RESULT_CACHE_PREFIX}{digest}"


async def get_cached_response(key: str) -> ChatResponse | None:
    try:
        redis = await get_redis()
        data = await redis.get(key)
    except Exception:
        return None
    if not data:
        return None
    if isinstance(data, bytes):
        data = data.decode()
    try:
        return ChatResponse.model_validate_json(data)
    except Exception:
        return None


async def set_cached_response(key: str, response: ChatResponse, ttl: int = 300) -> None:
    try:
        redis = await get_redis()
        await redis.setex(key, ttl, response.model_dump_json())
    except Exception:
        return
