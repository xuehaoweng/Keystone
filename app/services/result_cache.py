import asyncio
import hashlib
from collections.abc import Awaitable, Callable

from app.db.redis import get_redis
from app.models.request import ChatRequest
from app.models.response import ChatResponse

RESULT_CACHE_PREFIX = "result:"

_inflight: dict[str, asyncio.Future[ChatResponse]] = {}
_inflight_lock = asyncio.Lock()


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


async def get_or_compute(
    key: str,
    compute: Callable[[], Awaitable[ChatResponse]],
    on_cache_hit: Callable[[ChatResponse], Awaitable[None]] | None = None,
) -> ChatResponse:
    """Return cached result if present, otherwise run *compute*.

    If another coroutine is already computing the same *key*, wait for
    its result instead of issuing a duplicate backend request.
    """
    cached = await get_cached_response(key)
    if cached:
        if on_cache_hit:
            await on_cache_hit(cached)
        return cached

    async with _inflight_lock:
        if key in _inflight:
            future = _inflight[key]
            return await future
        future = asyncio.get_event_loop().create_future()
        _inflight[key] = future

    try:
        result = await compute()
        await set_cached_response(key, result)
        future.set_result(result)
    except Exception as exc:
        future.set_exception(exc)
        raise
    finally:
        async with _inflight_lock:
            _inflight.pop(key, None)

    return result
