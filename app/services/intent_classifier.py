import hashlib
import json
from contextlib import suppress

import httpx

from app.adapters.base import AdapterRegistry, ChatResult, ModelConfig
from app.config import get_gateway_config
from app.db.redis import get_redis
from app.models.request import IntentResult

INTENT_CACHE_PREFIX = "intent:"


def _content_hash(messages: list[dict]) -> str:
    content = messages[0].get("content", "")[:200] if messages else ""
    return hashlib.md5(content.encode()).hexdigest()


async def get_cached_intent(messages: list[dict]) -> IntentResult | None:
    r = await get_redis()
    key = f"{INTENT_CACHE_PREFIX}{_content_hash(messages)}"
    data = await r.get(key)
    if data:
        with suppress(Exception):
            return IntentResult(**json.loads(data))
    return None


async def cache_intent(messages: list[dict], intent: IntentResult, ttl: int = 300) -> None:
    r = await get_redis()
    key = f"{INTENT_CACHE_PREFIX}{_content_hash(messages)}"
    await r.setex(key, ttl, intent.model_dump_json())


async def classify_intent(messages: list[dict]) -> IntentResult:
    cached = await get_cached_intent(messages)
    if cached:
        return cached

    cfg = get_gateway_config()
    timeout = cfg.get("timeouts", {}).get("intent_classification", 2)
    model_name = cfg.get("intent_classifier", {}).get("model", "claude-haiku")
    prompt = cfg.get("intent_classifier", {}).get("prompt", "")
    cache_ttl = cfg.get("intent_classifier", {}).get("cache_ttl", 300)

    adapter_cls = AdapterRegistry.get("openai")
    intent_model = ModelConfig(name=model_name, provider="openai", tier="cheap")
    adapter = adapter_cls(intent_model)

    system_msg = {"role": "system", "content": prompt}
    user_msg = {"role": "user", "content": json.dumps({"messages": messages})}

    try:
        import asyncio
        result: ChatResult = await asyncio.wait_for(
            adapter.chat(messages=[system_msg, user_msg], stream=False, temperature=0, max_tokens=100),
            timeout=timeout,
        )
        parsed = json.loads(result.content.strip())
        intent = IntentResult(
            tier=parsed.get("tier", "cheap"),
            task_type=parsed.get("task_type", "unknown"),
            fallback_model=parsed.get("fallback_model"),
        )
    except (json.JSONDecodeError, KeyError, httpx.HTTPError, TimeoutError, Exception):
        intent = IntentResult(tier="cheap", task_type="unknown")

    await cache_intent(messages, intent, cache_ttl)
    return intent
