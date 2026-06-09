# LLM Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建统一大模型调度网关，实现按需路由、负载均衡、统一鉴权，支持流式/非流式响应。

**Architecture:** FastAPI asyncio 原生异步架构。请求经过鉴权中间件 → 规则引擎匹配 → 意图分类兜底 → 路由器选择模型 → 负载均衡选实例 → 模型适配器调用 → SSE/同步返回。BackgroundTasks 异步记录日志和用量。

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, pydantic v2, httpx, redis, pyyaml, python-jose, pytest, pytest-asyncio

---

## File Structure

```
llm_gateway/
├── pyproject.toml                          # 项目配置 + 依赖
├── config/
│   ├── gateway.yaml                        # 网关配置（限流、超时、意图分类 prompt）
│   └── models.yaml                         # 模型配置（providers, tiers, weights）
├── app/
│   ├── __init__.py
│   ├── main.py                             # FastAPI 入口，路由注册，生命周期事件
│   ├── config.py                           # YAML 配置加载
│   ├── models/
│   │   ├── __init__.py
│   │   ├── request.py                      # Pydantic 请求模型
│   │   └── response.py                     # Pydantic 响应模型
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py                         # ModelAdapter 抽象基类
│   │   ├── openai_adapter.py               # OpenAI/GPT 适配器
│   │   ├── anthropic_adapter.py            # Anthropic Claude 适配器
│   │   └── qwen_adapter.py                 # 通义千问适配器
│   ├── services/
│   │   ├── __init__.py
│   │   ├── rule_engine.py                  # YAML 规则引擎
│   │   ├── intent_classifier.py            # 意图分类 + Redis 缓存
│   │   ├── router.py                       # 路由决策（规则 + 意图 + 用户偏好）
│   │   ├── load_balancer.py                # 加权轮询 + 最少连接
│   │   ├── dispatcher.py                   # asyncio 调度器（流式/非流式）
│   │   └── metrics.py                      # 用量统计
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py                         # API Key + JWT 鉴权中间件
│   │   └── rate_limit.py                   # Redis 滑动窗口限流
│   ├── api/
│   │   ├── __init__.py
│   │   ├── runs.py                         # /api/runs 端点
│   │   ├── auth.py                         # /api/auth 端点
│   │   └── admin.py                        # /api/models, /api/metrics 端点
│   └── db/
│       ├── __init__.py
│       ├── redis.py                        # Redis 连接管理
│       └── sqlite.py                       # SQLite 连接 + 表初始化
├── tests/
│   ├── conftest.py                         # 共享 fixtures
│   ├── test_rule_engine.py
│   ├── test_intent_classifier.py
│   ├── test_load_balancer.py
│   ├── test_router.py
│   ├── test_adapters.py
│   ├── test_dispatcher.py
│   ├── test_auth_middleware.py
│   ├── test_api_runs.py
│   └── test_api_auth.py
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## 任务分解

任务按依赖顺序排列。每个任务可独立测试、可独立提交。
测试中涉及外部 HTTP 调用的（如意图分类、模型调用），使用 `pytest-httpx` 或 `unittest.mock` 模拟。
Redis 在测试中使用 fakeredis 或 mock。SQLite 使用内存数据库。

---

### Task 3: 模型适配器基类 + OpenAI 适配器

**Files:**
- Create: `app/adapters/__init__.py`
- Create: `app/adapters/base.py`
- Create: `app/adapters/openai_adapter.py`
- Create: `app/adapters/anthropic_adapter.py`
- Create: `app/adapters/qwen_adapter.py`
- Test: `tests/test_adapters.py`

- [ ] **Step 1: 创建 app/adapters/__init__.py**

```python
from app.adapters.anthropic_adapter import AnthropicAdapter
from app.adapters.base import AdapterRegistry, ModelAdapter, get_adapter
from app.adapters.openai_adapter import OpenAIAdapter
from app.adapters.qwen_adapter import QwenAdapter

__all__ = [
    "ModelAdapter",
    "AdapterRegistry",
    "get_adapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "QwenAdapter",
]
```

- [ ] **Step 2: 创建 app/adapters/base.py**

```python
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

from app.config import get_models_config


@dataclass
class ModelConfig:
    name: str
    provider: str
    tier: str
    weight: int = 1
    max_concurrent: int = 100
    rate_limit: int = 1000


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    finish_reason: str = "stop"


@dataclass
class ChatChunk:
    content: str = ""
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelAdapter(ABC):
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        self._api_keys = self._load_api_keys()

    def _load_api_keys(self) -> list[str]:
        provider_cfg = get_models_config().get("providers", {}).get(self.model_config.provider, {})
        env_key = f"{self.model_config.provider.upper()}_API_KEY"
        env_keys = os.getenv(env_key, "")
        keys = [k.strip() for k in env_keys.split(",") if k.strip()]
        config_keys = provider_cfg.get("api_keys", [])
        return keys + config_keys if keys else config_keys

    def _get_api_key(self) -> str:
        if not self._api_keys:
            raise RuntimeError(f"No API keys configured for provider: {self.model_config.provider}")
        return self._api_keys[0]

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        stream: bool = False,
        **kwargs,
    ) -> ChatResult | AsyncIterator[ChatChunk]:
        ...


class AdapterRegistry:
    _adapters: dict[str, type[ModelAdapter]] = {}

    @classmethod
    def register(cls, provider: str, adapter_cls: type[ModelAdapter]):
        cls._adapters[provider] = adapter_cls

    @classmethod
    def get(cls, provider: str) -> type[ModelAdapter]:
        adapter_cls = cls._adapters.get(provider)
        if not adapter_cls:
            raise ValueError(f"No adapter registered for provider: {provider}")
        return adapter_cls


def get_adapter(model_name: str) -> ModelAdapter:
    models = get_models_config().get("models", [])
    model_cfg = next((m for m in models if m["name"] == model_name), None)
    if not model_cfg:
        raise ValueError(f"Model not found in config: {model_name}")
    mc = ModelConfig(
        name=model_cfg["name"],
        provider=model_cfg["provider"],
        tier=model_cfg["tier"],
        weight=model_cfg.get("weight", 1),
        max_concurrent=model_cfg.get("max_concurrent", 100),
        rate_limit=model_cfg.get("rate_limit", 1000),
    )
    adapter_cls = AdapterRegistry.get(mc.provider)
    return adapter_cls(mc)
```

- [ ] **Step 3: 创建 app/adapters/openai_adapter.py**

```python
import json
from typing import AsyncIterator

import httpx

from app.adapters.base import ChatChunk, ChatResult, ModelAdapter
from app.config import get_models_config


class OpenAIAdapter(ModelAdapter):
    async def chat(
        self,
        messages: list[dict],
        stream: bool = False,
        **kwargs,
    ) -> ChatResult | AsyncIterator[ChatChunk]:
        if stream:
            return self._stream(messages, **kwargs)
        return await self._non_stream(messages, **kwargs)

    async def _non_stream(self, messages: list[dict], **kwargs) -> ChatResult:
        provider_cfg = get_models_config()["providers"][self.model_config.provider]
        url = f"{provider_cfg['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model_config.name,
            "messages": messages,
            "stream": False,
            **kwargs,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=body, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return ChatResult(
            content=choice["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            model=data.get("model", self.model_config.name),
            finish_reason=choice.get("finish_reason", "stop"),
        )

    async def _stream(self, messages: list[dict], **kwargs) -> AsyncIterator[ChatChunk]:
        provider_cfg = get_models_config()["providers"][self.model_config.provider]
        url = f"{provider_cfg['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model_config.name,
            "messages": messages,
            "stream": True,
            **kwargs,
        }
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, headers=headers, json=body, timeout=60) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    content = delta.get("content", "") or ""
                    finish_reason = choice.get("finish_reason")
                    if content or finish_reason:
                        yield ChatChunk(content=content, finish_reason=finish_reason)
```

- [ ] **Step 4: 创建 app/adapters/anthropic_adapter.py**

```python
import json
from typing import AsyncIterator

import httpx

from app.adapters.base import ChatChunk, ChatResult, ModelAdapter
from app.config import get_models_config


class AnthropicAdapter(ModelAdapter):
    API_VERSION = "2023-06-01"

    async def chat(
        self,
        messages: list[dict],
        stream: bool = False,
        **kwargs,
    ) -> ChatResult | AsyncIterator[ChatChunk]:
        if stream:
            return self._stream(messages, **kwargs)
        return await self._non_stream(messages, **kwargs)

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        system_prompt = None
        converted = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            elif msg["role"] in ("user", "assistant"):
                converted.append({"role": msg["role"], "content": msg["content"]})
        return system_prompt, converted

    async def _non_stream(self, messages: list[dict], **kwargs) -> ChatResult:
        provider_cfg = get_models_config()["providers"][self.model_config.provider]
        url = f"{provider_cfg['base_url']}/v1/messages"
        system_prompt, converted = self._convert_messages(messages)
        headers = {
            "x-api-key": self._get_api_key(),
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self.model_config.name,
            "messages": converted,
            "max_tokens": kwargs.pop("max_tokens", 4096),
            **kwargs,
        }
        if system_prompt:
            body["system"] = system_prompt
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=body, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        content = data["content"][0]["text"]
        usage = data.get("usage", {})
        return ChatResult(
            content=content,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            model=self.model_config.name,
            finish_reason=data.get("stop_reason", "end_turn"),
        )

    async def _stream(self, messages: list[dict], **kwargs) -> AsyncIterator[ChatChunk]:
        provider_cfg = get_models_config()["providers"][self.model_config.provider]
        url = f"{provider_cfg['base_url']}/v1/messages"
        system_prompt, converted = self._convert_messages(messages)
        headers = {
            "x-api-key": self._get_api_key(),
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self.model_config.name,
            "messages": converted,
            "max_tokens": kwargs.pop("max_tokens", 4096),
            "stream": True,
            **kwargs,
        }
        if system_prompt:
            body["system"] = system_prompt
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, headers=headers, json=body, timeout=60) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    event_type = data.get("type", "")
                    if event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield ChatChunk(content=delta.get("text", ""))
                    elif event_type == "message_delta":
                        stop_reason = data.get("delta", {}).get("stop_reason")
                        usage = data.get("usage", {})
                        if stop_reason:
                            yield ChatChunk(
                                content="",
                                finish_reason=stop_reason,
                                prompt_tokens=usage.get("input_tokens", 0),
                                completion_tokens=usage.get("output_tokens", 0),
                                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                            )
```

- [ ] **Step 5: 创建 app/adapters/qwen_adapter.py**

```python
from app.adapters.openai_adapter import OpenAIAdapter


class QwenAdapter(OpenAIAdapter):
    """Qwen uses OpenAI-compatible API."""
```

- [ ] **Step 6: 创建 tests/test_adapters.py**

```python
import pytest
import pytest_httpx

from app.adapters.anthropic_adapter import AnthropicAdapter
from app.adapters.base import AdapterRegistry, ChatResult, ModelConfig
from app.adapters.openai_adapter import OpenAIAdapter
from app.adapters.qwen_adapter import QwenAdapter


@pytest.fixture
def openai_config():
    return ModelConfig(name="gpt-4o-mini", provider="openai", tier="cheap")


@pytest.fixture
def anthropic_config():
    return ModelConfig(name="claude-haiku", provider="anthropic", tier="cheap")


@pytest.fixture(autouse=True)
def register_adapters():
    AdapterRegistry.register("openai", OpenAIAdapter)
    AdapterRegistry.register("anthropic", AnthropicAdapter)
    AdapterRegistry.register("qwen", QwenAdapter)
    yield


def test_adapter_registry():
    assert AdapterRegistry.get("openai") is OpenAIAdapter
    assert AdapterRegistry.get("anthropic") is AnthropicAdapter


def test_adapter_registry_missing():
    with pytest.raises(ValueError, match="No adapter registered"):
        AdapterRegistry.get("unknown")


@pytest.mark.asyncio
async def test_openai_non_stream(httpx_mock: pytest_httpx.HTTPXMock, openai_config, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    httpx_mock.add_response(
        json={
            "id": "chat-123",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )
    adapter = OpenAIAdapter(openai_config)
    result = await adapter.chat(messages=[{"role": "user", "content": "Hi"}])
    assert isinstance(result, ChatResult)
    assert result.content == "Hello"
    assert result.total_tokens == 15


@pytest.mark.asyncio
async def test_openai_non_stream_no_api_key(openai_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adapter = OpenAIAdapter(openai_config)
    adapter._api_keys = []
    with pytest.raises(RuntimeError, match="No API keys configured"):
        await adapter.chat(messages=[{"role": "user", "content": "Hi"}])


@pytest.mark.asyncio
async def test_qwen_adapter_inherits_openai(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "test-key")
    assert issubclass(QwenAdapter, OpenAIAdapter)
```

- [ ] **Step 7: Run tests**

```bash
cd /root/llm_gateway && pytest tests/test_adapters.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 8: Commit**

```bash
git add app/adapters/ tests/test_adapters.py
git commit -m "feat: model adapters (OpenAI, Anthropic, Qwen) with registry"
```

---

### Task 4: 规则引擎

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/rule_engine.py`
- Test: `tests/test_rule_engine.py`

- [ ] **Step 1: 创建 app/services/__init__.py**

```python
```

- [ ] **Step 2: 创建 app/services/rule_engine.py**

```python
import fnmatch
from dataclasses import dataclass


@dataclass
class RuleMatch:
    matched: bool
    rule_name: str = ""
    tier: str = ""


def _content_text(messages: list[dict]) -> str:
    return " ".join(m.get("content", "") for m in messages)


def _tools_match(rule_tools: list[str], request_tools: list[str]) -> bool:
    for rt in request_tools:
        tool_name = rt if isinstance(rt, str) else (rt.get("name", "") if isinstance(rt, dict) else "")
        for pattern in rule_tools:
            if fnmatch.fnmatch(tool_name, pattern):
                return True
    return False


def _keywords_match(rule_keywords: list[str], text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in rule_keywords)


def evaluate_rules(messages: list[dict], tools: list[str] | None = None) -> RuleMatch:
    from app.config import get_gateway_config

    rules = get_gateway_config().get("rules", [])
    if not rules:
        return RuleMatch(matched=False)

    text = _content_text(messages)

    for rule in rules:
        match_cfg = rule.get("match", {})

        if "tools" in match_cfg:
            if not tools or not _tools_match(match_cfg["tools"], tools):
                continue

        if "keywords" in match_cfg:
            if not _keywords_match(match_cfg["keywords"], text):
                continue

        word_count = len(text.split())
        if "max_content_tokens" in match_cfg and word_count > match_cfg["max_content_tokens"]:
            continue
        if "min_content_tokens" in match_cfg and word_count < match_cfg["min_content_tokens"]:
            continue

        return RuleMatch(matched=True, rule_name=rule["name"], tier=rule["tier"])

    return RuleMatch(matched=False)
```

- [ ] **Step 3: 创建 tests/test_rule_engine.py**

```python
from app.services.rule_engine import RuleMatch, evaluate_rules


def test_tool_match_db_query():
    result = evaluate_rules(
        messages=[{"role": "user", "content": "run query"}],
        tools=["execute_sql"],
    )
    assert result.matched is True
    assert result.rule_name == "db_query"
    assert result.tier == "cheap"


def test_tool_match_mcp():
    result = evaluate_rules(
        messages=[{"role": "user", "content": "call mcp"}],
        tools=["mcp_search"],
    )
    assert result.matched is True
    assert result.tier == "cheap"


def test_keyword_match_alert():
    result = evaluate_rules(
        messages=[{"role": "user", "content": "分析这个告警：CPU使用率超过90%"}],
    )
    assert result.matched is True
    assert result.rule_name == "alert_analysis"
    assert result.tier == "expensive"


def test_no_tool_no_keyword_short_text():
    result = evaluate_rules(
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result.matched is True
    assert result.tier == "cheap"


def test_unmatched_when_no_rules_apply(monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", "/tmp/test_no_rules")
    import yaml, os
    os.makedirs("/tmp/test_no_rules", exist_ok=True)
    with open("/tmp/test_no_rules/gateway.yaml", "w") as f:
        yaml.dump({"server": {"host": "0.0.0.0", "port": 8000}}, f)
    with open("/tmp/test_no_rules/models.yaml", "w") as f:
        yaml.dump({"models": [], "providers": {}}, f)
    from app.config import reload_config
    reload_config()
    result = evaluate_rules(messages=[{"role": "user", "content": "test"}])
    assert result.matched is False
```

- [ ] **Step 4: Run tests**

```bash
cd /root/llm_gateway && pytest tests/test_rule_engine.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/__init__.py app/services/rule_engine.py tests/test_rule_engine.py
git commit -m "feat: rule engine with tool/keyword matching"
```

---

### Task 5: 意图分类 + Redis 缓存

**Files:**
- Create: `app/db/__init__.py`
- Create: `app/db/redis.py`
- Create: `app/services/intent_classifier.py`
- Test: `tests/test_intent_classifier.py`

- [ ] **Step 1: 创建 app/db/__init__.py**

```python
```

- [ ] **Step 2: 创建 app/db/redis.py**

```python
import os

import redis.asyncio as redis

_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis = redis.from_url(url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
```

- [ ] **Step 3: 创建 app/services/intent_classifier.py**

```python
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
```

- [ ] **Step 4: 创建 tests/test_intent_classifier.py**

```python
import json
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest

from app.adapters.base import AdapterRegistry, ChatResult, ModelConfig
from app.adapters.openai_adapter import OpenAIAdapter
from app.db.redis import get_redis
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
```

- [ ] **Step 5: Run tests**

```bash
cd /root/llm_gateway && pytest tests/test_intent_classifier.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/db/ app/services/intent_classifier.py tests/test_intent_classifier.py
git commit -m "feat: intent classifier with Redis cache and timeout fallback"
```

---

### Task 6: 路由器 + 负载均衡器

**Files:**
- Create: `app/services/load_balancer.py`
- Create: `app/services/router.py`
- Test: `tests/test_load_balancer.py`
- Test: `tests/test_router.py`

- [ ] **Step 1: 创建 app/services/load_balancer.py**

```python
import asyncio
import time
from dataclasses import dataclass

from app.config import get_models_config


@dataclass
class ModelInstance:
    name: str
    provider: str
    tier: str
    weight: int = 1
    max_concurrent: int = 100
    rate_limit: int = 1000
    current_connections: int = 0
    error_count: int = 0
    last_error_time: float = 0
    healthy: bool = True


class LoadBalancer:
    def __init__(self):
        self._instances: dict[str, ModelInstance] = {}
        self._lock = asyncio.Lock()
        self._reload()

    def _reload(self):
        models = get_models_config().get("models", [])
        for m in models:
            if m["name"] in self._instances:
                inst = self._instances[m["name"]]
                inst.weight = m.get("weight", 1)
                inst.max_concurrent = m.get("max_concurrent", 100)
                inst.rate_limit = m.get("rate_limit", 1000)
            else:
                self._instances[m["name"]] = ModelInstance(
                    name=m["name"],
                    provider=m["provider"],
                    tier=m["tier"],
                    weight=m.get("weight", 1),
                    max_concurrent=m.get("max_concurrent", 100),
                    rate_limit=m.get("rate_limit", 1000),
                )

    def get_by_tier(self, tier: str) -> list[ModelInstance]:
        return [i for i in self._instances.values() if i.tier == tier and i.healthy]

    async def select(self, tier: str) -> ModelInstance | None:
        async with self._lock:
            candidates = self.get_by_tier(tier)
            if not candidates:
                return None
            available = [i for i in candidates if i.current_connections < i.max_concurrent]
            if not available:
                available = candidates
            available.sort(key=lambda i: (i.current_connections / max(i.weight, 1), i.current_connections))
            selected = available[0]
            selected.current_connections += 1
            return selected

    def release(self, model_name: str):
        if model_name in self._instances:
            inst = self._instances[model_name]
            inst.current_connections = max(0, inst.current_connections - 1)

    def report_error(self, model_name: str):
        if model_name in self._instances:
            inst = self._instances[model_name]
            inst.error_count += 1
            inst.last_error_time = time.time()
            if inst.error_count >= 5:
                inst.healthy = False

    def report_success(self, model_name: str):
        if model_name in self._instances:
            inst = self._instances[model_name]
            inst.error_count = 0
            inst.healthy = True

    def get_all(self) -> dict:
        return {
            name: {
                "tier": i.tier,
                "healthy": i.healthy,
                "connections": i.current_connections,
                "errors": i.error_count,
            }
            for name, i in self._instances.items()
        }


_lb: LoadBalancer | None = None


def get_load_balancer() -> LoadBalancer:
    global _lb
    if _lb is None:
        _lb = LoadBalancer()
    return _lb
```

- [ ] **Step 2: 创建 tests/test_load_balancer.py**

```python
import asyncio

import pytest

from app.services.load_balancer import LoadBalancer, ModelInstance, get_load_balancer


@pytest.fixture
def lb():
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "m1": ModelInstance(name="m1", provider="openai", tier="cheap", weight=1),
        "m2": ModelInstance(name="m2", provider="openai", tier="cheap", weight=2),
        "m3": ModelInstance(name="m3", provider="openai", tier="expensive", weight=1),
    }
    lb._lock = asyncio.Lock()
    return lb


@pytest.mark.asyncio
async def test_select_from_tier(lb):
    result = await lb.select("cheap")
    assert result is not None
    assert result.tier == "cheap"


@pytest.mark.asyncio
async def test_select_returns_none_for_empty_tier(lb):
    result = await lb.select("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_select_respects_capacity(lb):
    lb._instances["m1"].max_concurrent = 1
    lb._instances["m1"].current_connections = 1
    result = await lb.select("cheap")
    assert result.name == "m2"


@pytest.mark.asyncio
async def test_release_decreases_connections(lb):
    selected = await lb.select("cheap")
    assert selected.current_connections == 1
    lb.release(selected.name)
    assert lb._instances[selected.name].current_connections == 0


def test_report_error_marks_unhealthy(lb):
    for _ in range(5):
        lb.report_error("m1")
    assert lb._instances["m1"].healthy is False


def test_report_success_resets(lb):
    for _ in range(5):
        lb.report_error("m1")
    lb.report_success("m1")
    assert lb._instances["m1"].healthy is True
    assert lb._instances["m1"].error_count == 0


def test_get_all(lb):
    result = lb.get_all()
    assert "m1" in result
    assert result["m1"]["tier"] == "cheap"
```

- [ ] **Step 3: 创建 app/services/router.py**

```python
from app.models.request import ChatRequest, IntentResult
from app.services.intent_classifier import classify_intent
from app.services.load_balancer import ModelInstance, get_load_balancer
from app.services.rule_engine import evaluate_rules


async def resolve_route(request: ChatRequest) -> ModelInstance:
    lb = get_load_balancer()

    # 1. Check user's preferred model
    if request.preferred_model:
        all_status = lb.get_all()
        if request.preferred_model in all_status:
            instance = lb._instances.get(request.preferred_model)
            if instance and instance.healthy:
                instance.current_connections += 1
                return instance

    # 2. Determine tier
    tier = request.model_tier
    if tier == "auto":
        tool_names = [t.name for t in request.tools] if request.tools else []
        rule_result = evaluate_rules(
            [m.model_dump() for m in request.messages],
            tools=tool_names,
        )
        if rule_result.matched:
            tier = rule_result.tier
        else:
            intent: IntentResult = await classify_intent(
                [m.model_dump() for m in request.messages]
            )
            tier = intent.tier

    # 3. Load balancer selects instance
    instance = await lb.select(tier)
    if not instance:
        fallback = "cheap" if tier == "expensive" else "expensive"
        instance = await lb.select(fallback)
    if not instance:
        raise RuntimeError("No available model instances")

    return instance
```

- [ ] **Step 4: 创建 tests/test_router.py**

```python
import asyncio

import pytest

from app.models.request import ChatRequest, Message
from app.services.load_balancer import LoadBalancer, ModelInstance
from app.services.router import resolve_route


@pytest.fixture
def lb(monkeypatch):
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "gpt-4o-mini": ModelInstance(name="gpt-4o-mini", provider="openai", tier="cheap", weight=3),
        "claude-opus": ModelInstance(name="claude-opus", provider="anthropic", tier="expensive", weight=1),
    }
    lb._lock = asyncio.Lock()
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)
    return lb


@pytest.mark.asyncio
async def test_resolve_with_explicit_tier(lb):
    req = ChatRequest(
        messages=[Message(role="user", content="Hello")],
        model_tier="cheap",
    )
    result = await resolve_route(req)
    assert result.tier == "cheap"


@pytest.mark.asyncio
async def test_resolve_preferred_model(lb):
    req = ChatRequest(
        messages=[Message(role="user", content="Hello")],
        preferred_model="claude-opus",
    )
    result = await resolve_route(req)
    assert result.name == "claude-opus"


@pytest.mark.asyncio
async def test_resolve_no_instances_raises(lb):
    for inst in lb._instances.values():
        inst.current_connections = 999
        inst.max_concurrent = 1
    with pytest.raises(RuntimeError, match="No available model instances"):
        await resolve_route(
            ChatRequest(messages=[Message(role="user", content="Hello")], model_tier="cheap")
        )
```

- [ ] **Step 5: Run tests**

```bash
cd /root/llm_gateway && pytest tests/test_load_balancer.py tests/test_router.py -v
```

Expected: All 10 tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/load_balancer.py app/services/router.py tests/test_load_balancer.py tests/test_router.py
git commit -m "feat: load balancer and router with tier selection"
```

---

### Task 7: Dispatcher + 流式/非流式处理

**Files:**
- Create: `app/services/dispatcher.py`
- Create: `app/services/metrics.py`
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: 创建 app/services/metrics.py**

```python
import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RequestMetric:
    user_id: str
    model_name: str
    tier: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    is_stream: bool
    route_path: str  # "rule:{name}" | "intent" | "preferred"
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    def __init__(self):
        self._metrics: list[RequestMetric] = []
        self._user_usage: dict[str, dict] = defaultdict(lambda: {
            "total_tokens": 0,
            "total_requests": 0,
            "total_cost_estimate": 0.0,
        })

    def record(self, metric: RequestMetric):
        self._metrics.append(metric)
        usage = self._user_usage[metric.user_id]
        usage["total_tokens"] += metric.total_tokens
        usage["total_requests"] += 1

    def get_user_usage(self, user_id: str) -> dict:
        return self._user_usage.get(user_id, {})

    def get_summary(self) -> dict:
        total = len(self._metrics)
        if total == 0:
            return {"total_requests": 0}
        return {
            "total_requests": total,
            "avg_latency_ms": sum(m.latency_ms for m in self._metrics) / total,
            "total_tokens": sum(m.total_tokens for m in self._metrics),
        }


_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics
```

- [ ] **Step 2: 创建 app/services/dispatcher.py**

```python
import asyncio
import time
import uuid

from fastapi import BackgroundTasks

from app.adapters.base import ChatChunk, ChatResult, ModelAdapter
from app.models.request import ChatRequest, Message
from app.services.load_balancer import get_load_balancer
from app.services.metrics import MetricsCollector, RequestMetric, get_metrics


def _messages_to_dict(messages: list[Message]) -> list[dict]:
    return [m.model_dump() for m in messages]


async def dispatch_non_stream(
    adapter: ModelAdapter,
    request: ChatRequest,
    model_name: str,
    tier: str,
    route_path: str,
    user_id: str,
    lb,
    metrics: MetricsCollector,
) -> ChatResult:
    start = time.time()
    messages = _messages_to_dict(request.messages)
    try:
        result = await adapter.chat(
            messages=messages,
            stream=False,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        lb.report_success(model_name)
        latency = (time.time() - start) * 1000
        metrics.record(RequestMetric(
            user_id=user_id,
            model_name=model_name,
            tier=tier,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_ms=latency,
            is_stream=False,
            route_path=route_path,
        ))
        return result
    except Exception as e:
        lb.report_error(model_name)
        raise


async def dispatch_stream(
    adapter: ModelAdapter,
    request: ChatRequest,
    model_name: str,
    tier: str,
    route_path: str,
    user_id: str,
    lb,
    metrics: MetricsCollector,
):
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    messages = _messages_to_dict(request.messages)
    total_prompt = 0
    total_completion = 0
    start = time.time()
    try:
        async for chunk in adapter.chat(
            messages=messages,
            stream=True,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        ):
            total_completion += chunk.completion_tokens
            if chunk.content:
                yield f"event: chunk\ndata: {{"id": "{run_id}", "model": "{model_name}", "content": {json.dumps(chunk.content)}, "finish_reason": {json.dumps(chunk.finish_reason)}}}\n\n"
            if chunk.finish_reason:
                total_prompt = chunk.prompt_tokens
                yield f"event: done\ndata: {{"id": "{run_id}", "model": "{model_name}", "finish_reason": {json.dumps(chunk.finish_reason)}}}\n\n"
        lb.report_success(model_name)
        latency = (time.time() - start) * 1000
        metrics.record(RequestMetric(
            user_id=user_id,
            model_name=model_name,
            tier=tier,
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            total_tokens=total_prompt + total_completion,
            latency_ms=latency,
            is_stream=True,
            route_path=route_path,
        ))
    except asyncio.CancelledError:
        lb.release(model_name)
        raise
    except Exception as e:
        lb.report_error(model_name)
        raise


import json  # noqa: E402
```

Wait, the import needs to be at the top. Let me fix:

```python
import asyncio
import json
import time
import uuid

from fastapi import BackgroundTasks

from app.adapters.base import ChatChunk, ChatResult, ModelAdapter
from app.models.request import ChatRequest, Message
from app.services.load_balancer import get_load_balancer
from app.services.metrics import MetricsCollector, RequestMetric, get_metrics
```

- [ ] **Step 3: 创建 tests/test_dispatcher.py**

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import ChatChunk, ChatResult, ModelConfig
from app.models.request import ChatRequest, Message
from app.services.metrics import MetricsCollector


@pytest.fixture
def mock_adapter():
    adapter = AsyncMock()
    adapter.chat = AsyncMock()
    return adapter


@pytest.fixture
def mock_lb():
    lb = MagicMock()
    lb.report_success = MagicMock()
    lb.report_error = MagicMock()
    lb.release = MagicMock()
    return lb


@pytest.fixture
def mock_metrics():
    return MetricsCollector()


@pytest.mark.asyncio
async def test_dispatch_non_stream_success(mock_adapter, mock_lb, mock_metrics):
    from app.services.dispatcher import dispatch_non_stream
    mock_adapter.chat.return_value = ChatResult(
        content="Hello",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        model="gpt-4o-mini",
    )
    request = ChatRequest(messages=[Message(role="user", content="Hi")])
    result = await dispatch_non_stream(
        adapter=mock_adapter,
        request=request,
        model_name="gpt-4o-mini",
        tier="cheap",
        route_path="rule:general_query",
        user_id="user-1",
        lb=mock_lb,
        metrics=mock_metrics,
    )
    assert result.content == "Hello"
    mock_lb.report_success.assert_called_once_with("gpt-4o-mini")
    assert mock_metrics.get_summary()["total_requests"] == 1


@pytest.mark.asyncio
async def test_dispatch_non_stream_error(mock_adapter, mock_lb, mock_metrics):
    from app.services.dispatcher import dispatch_non_stream
    mock_adapter.chat.side_effect = RuntimeError("API error")
    request = ChatRequest(messages=[Message(role="user", content="Hi")])
    with pytest.raises(RuntimeError, match="API error"):
        await dispatch_non_stream(
            adapter=mock_adapter,
            request=request,
            model_name="gpt-4o-mini",
            tier="cheap",
            route_path="rule:general_query",
            user_id="user-1",
            lb=mock_lb,
            metrics=mock_metrics,
        )
    mock_lb.report_error.assert_called_once_with("gpt-4o-mini")


@pytest.mark.asyncio
async def test_dispatch_stream_yields_chunks(mock_adapter, mock_lb, mock_metrics):
    from app.services.dispatcher import dispatch_stream
    async def mock_stream(**kwargs):
        yield ChatChunk(content="Hel")
        yield ChatChunk(content="lo")
        yield ChatChunk(content="", finish_reason="stop")
    mock_adapter.chat = mock_stream
    request = ChatRequest(messages=[Message(role="user", content="Hi")], stream=True)
    chunks = []
    async for chunk in dispatch_stream(
        adapter=mock_adapter,
        request=request,
        model_name="gpt-4o-mini",
        tier="cheap",
        route_path="rule:general_query",
        user_id="user-1",
        lb=mock_lb,
        metrics=mock_metrics,
    ):
        chunks.append(chunk)
    assert len(chunks) == 3
    assert "event: chunk" in chunks[0]
    assert "event: done" in chunks[-1]
    mock_lb.report_success.assert_called_once()
```

- [ ] **Step 4: Run tests**

```bash
cd /root/llm_gateway && pytest tests/test_dispatcher.py -v
```

Expected: All 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/dispatcher.py app/services/metrics.py tests/test_dispatcher.py
git commit -m "feat: dispatcher with stream/non-stream and metrics"
```

---

### Task 8: 鉴权中间件

**Files:**
- Create: `app/middleware/__init__.py`
- Create: `app/middleware/auth.py`
- Create: `app/middleware/rate_limit.py`
- Create: `app/db/sqlite.py`
- Test: `tests/test_auth_middleware.py`

- [ ] **Step 1: 创建 app/middleware/__init__.py**

```python
```

- [ ] **Step 2: 创建 app/db/sqlite.py**

```python
import aiosqlite

_db_path: str = "gateway.db"


def set_db_path(path: str):
    global _db_path
    _db_path = path


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(_db_path)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                key_hash TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT,
                quota_monthly INTEGER DEFAULT 0,
                rate_limit_rps INTEGER DEFAULT 10,
                allowed_tiers TEXT DEFAULT 'cheap,expensive',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_id TEXT,
                user_id TEXT,
                model_name TEXT,
                tier TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                latency_ms REAL,
                route_path TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
```

- [ ] **Step 3: 创建 app/middleware/auth.py**

```python
import hashlib
import uuid

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from app.config import get_gateway_config
from app.db.sqlite import get_db


def verify_api_key(key_hash: str) -> dict | None:
    """Look up API key hash in database. Returns user info or None."""
    import asyncio
    async def _lookup():
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT user_id, name, quota_monthly, rate_limit_rps, allowed_tiers FROM api_keys WHERE key_hash = ? AND active = 1",
                (key_hash,),
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "name": row[1],
                    "quota_monthly": row[2],
                    "rate_limit_rps": row[3],
                    "allowed_tiers": row[4].split(","),
                }
        return None
    return asyncio.get_event_loop().run_until_complete(_lookup())


def verify_jwt(token: str) -> dict | None:
    cfg = get_gateway_config()
    auth_cfg = cfg.get("auth", {})
    secret = auth_cfg.get("jwt_secret", "")
    if not secret:
        import os
        secret = os.getenv("GATEWAY_JWT_SECRET", "")
    if not secret:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=[auth_cfg.get("jwt_algorithm", "HS256")])
        return {"user_id": payload.get("sub"), "role": payload.get("role", "user")}
    except JWTError:
        return None


async def authenticate(request: Request) -> dict:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    token = auth_header[7:]

    # Try API key first
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    user_info = verify_api_key(key_hash)
    if user_info:
        request.state.user = user_info
        request.state.auth_type = "api_key"
        return user_info

    # Try JWT
    user_info = verify_jwt(token)
    if user_info:
        request.state.user = user_info
        request.state.auth_type = "jwt"
        return user_info

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


async def create_api_key(name: str, user_id: str, quota: int = 0, rate_limit: int = 10) -> dict:
    key = f"lgw_{uuid.uuid4().hex}"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO api_keys (id, key_hash, user_id, name, quota_monthly, rate_limit_rps) VALUES (?, ?, ?, ?, ?, ?)",
            (key_hash[:16], key_hash, user_id, name, quota, rate_limit),
        )
        await db.commit()
    return {"key": key, "id": key_hash[:16], "name": name}
```

- [ ] **Step 4: 创建 app/middleware/rate_limit.py**

```python
from fastapi import HTTPException, Request, status

from app.db.redis import get_redis


async def check_rate_limit(request: Request) -> None:
    user = getattr(request.state, "user", None)
    if not user:
        return
    user_id = user["user_id"]
    rps = user.get("rate_limit_rps", 10)
    r = await get_redis()
    key = f"ratelimit:{user_id}"
    current = await r.incr(key)
    if current == 1:
        await r.expire(key, 1)
    if current > rps:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({rps} rps)",
        )
```

- [ ] **Step 5: 创建 tests/test_auth_middleware.py**

```python
import hashlib
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from jose import jwt

from app.middleware.auth import authenticate, create_api_key, verify_jwt, verify_api_key


@pytest.fixture
def app():
    app = FastAPI()

    @app.get("/protected")
    async def protected(request):
        await authenticate(request)
        return {"user": request.state.user}

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_missing_auth_header(client):
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_invalid_api_key(client):
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


def test_verify_api_key_not_found():
    result = verify_api_key("nonexistent_hash")
    assert result is None


@pytest.mark.asyncio
async def test_create_api_key(monkeypatch):
    monkeypatch.setenv("SQLITE_DB_PATH", ":memory:")
    from app.db.sqlite import init_db
    await init_db()
    result = await create_api_key(name="test-key", user_id="user-1")
    assert result["key"].startswith("lgw_")
    assert result["name"] == "test-key"
```

- [ ] **Step 6: Run tests**

```bash
cd /root/llm_gateway && pytest tests/test_auth_middleware.py -v
```

Expected: All 6 tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/middleware/ app/db/sqlite.py tests/test_auth_middleware.py
git commit -m "feat: auth middleware (API Key + JWT) and rate limiting"
```

---

### Task 9: API 端点 + FastAPI 主入口

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/runs.py`
- Create: `app/api/auth.py`
- Create: `app/api/admin.py`
- Create: `app/main.py`
- Test: `tests/test_api_runs.py`
- Test: `tests/test_api_auth.py`

- [ ] **Step 1: 创建 app/api/__init__.py**

```python
```

- [ ] **Step 2: 创建 app/api/runs.py**

```python
import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.adapters.base import get_adapter
from app.middleware.auth import authenticate
from app.middleware.rate_limit import check_rate_limit
from app.models.request import ChatRequest
from app.models.response import ChatResponse, ChunkResponse, ErrorResponse, UsageInfo
from app.services.dispatcher import dispatch_non_stream, dispatch_stream
from app.services.load_balancer import get_load_balancer
from app.services.metrics import get_metrics
from app.services.router import resolve_route

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", status_code=status.HTTP_200_OK)
async def create_run(request: Request, body: ChatRequest):
    await authenticate(request)
    await check_rate_limit(request)
    user = request.state.user
    user_id = user["user_id"]

    lb = get_load_balancer()
    metrics = get_metrics()

    try:
        instance = await resolve_route(body)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        adapter = get_adapter(instance.name)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=500, detail=f"Adapter error: {e}")

    route_path = f"model:{instance.name}"

    if body.stream:
        return StreamingResponse(
            dispatch_stream(
                adapter=adapter,
                request=body,
                model_name=instance.name,
                tier=instance.tier,
                route_path=route_path,
                user_id=user_id,
                lb=lb,
                metrics=metrics,
            ),
            media_type="text/event-stream",
        )
    else:
        try:
            result = await dispatch_non_stream(
                adapter=adapter,
                request=body,
                model_name=instance.name,
                tier=instance.tier,
                route_path=route_path,
                user_id=user_id,
                lb=lb,
                metrics=metrics,
            )
            return ChatResponse(
                id=f"run-{instance.name}",
                model=instance.name,
                tier=instance.tier,
                content=result.content,
                usage=UsageInfo(
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    total_tokens=result.total_tokens,
                ),
                finish_reason=result.finish_reason,
            )
        except Exception as e:
            lb.release(instance.name)
            raise HTTPException(status_code=502, detail=f"Model error: {e}")
```

- [ ] **Step 3: 创建 app/api/auth.py**

```python
from fastapi import APIRouter, HTTPException, Request

from app.middleware.auth import authenticate, create_api_key
from app.db.sqlite import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/keys")
async def create_key(request: Request, name: str = "default", quota: int = 0, rate_limit: int = 10):
    await authenticate(request)
    user = request.state.user
    result = await create_api_key(name=name, user_id=user["user_id"], quota=quota, rate_limit=rate_limit)
    return result


@router.get("/keys")
async def list_keys(request: Request):
    await authenticate(request)
    user = request.state.user
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, quota_monthly, rate_limit_rps, allowed_tiers, created_at FROM api_keys WHERE user_id = ? AND active = 1",
            (user["user_id"],),
        )
        rows = await cursor.fetchall()
    return [
        {"id": r[0], "name": r[1], "quota_monthly": r[2], "rate_limit_rps": r[3], "allowed_tiers": r[4], "created_at": r[5]}
        for r in rows
    ]


@router.get("/keys/{key_id}/usage")
async def get_key_usage(key_id: str, request: Request):
    await authenticate(request)
    from app.services.metrics import get_metrics
    metrics = get_metrics()
    return metrics.get_user_usage(key_id)


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, request: Request):
    await authenticate(request)
    async with get_db() as db:
        await db.execute("UPDATE api_keys SET active = 0 WHERE id = ?", (key_id,))
        await db.commit()
    return {"deleted": True}
```

- [ ] **Step 4: 创建 app/api/admin.py**

```python
from fastapi import APIRouter, Request

from app.middleware.auth import authenticate
from app.services.load_balancer import get_load_balancer
from app.services.metrics import get_metrics

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/models")
async def list_models(request: Request):
    await authenticate(request)
    lb = get_load_balancer()
    return lb.get_all()


@router.get("/models/{model_name}/health")
async def model_health(model_name: str, request: Request):
    await authenticate(request)
    lb = get_load_balancer()
    all_status = lb.get_all()
    if model_name not in all_status:
        return {"name": model_name, "status": "unknown"}
    info = all_status[model_name]
    return {"name": model_name, **info, "status": "healthy" if info["healthy"] else "unhealthy"}


@router.get("/metrics")
async def get_metrics(request: Request):
    await authenticate(request)
    metrics = get_metrics()
    return metrics.get_summary()
```

- [ ] **Step 5: 创建 app/main.py**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.runs import router as runs_router
from app.db.redis import close_redis
from app.db.sqlite import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_redis()


app = FastAPI(title="LLM Gateway", version="0.1.0", lifespan=lifespan)

app.include_router(runs_router)
app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: 创建 tests/test_api_runs.py**

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app
from app.services.load_balancer import LoadBalancer, ModelInstance


@pytest.fixture
def client():
    # Patch auth to allow unauthenticated access in tests
    with patch("app.api.runs.authenticate", new=AsyncMock(return_value={"user_id": "test"})):
        with patch("app.api.runs.check_rate_limit", new=AsyncMock()):
            yield TestClient(app)


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


def test_create_run_no_auth(client):
    # Without auth patch, should return 401
    resp = client.post("/api/runs", json={
        "messages": [{"role": "user", "content": "Hi"}]
    })
    assert resp.status_code == 401
```

- [ ] **Step 7: 创建 tests/test_api_auth.py**

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app


@pytest.fixture
def client():
    with patch("app.api.auth.authenticate", new=AsyncMock(return_value={"user_id": "test"})):
        yield TestClient(app)


def test_list_keys_empty(client):
    resp = client.get("/api/auth/keys")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_models(client):
    resp = client.get("/api/models")
    assert resp.status_code == 200


def test_metrics_endpoint(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
```

- [ ] **Step 8: Run tests**

```bash
cd /root/llm_gateway && pytest tests/test_api_runs.py tests/test_api_auth.py -v
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add app/api/ app/main.py tests/test_api_runs.py tests/test_api_auth.py
git commit -m "feat: API endpoints (runs, auth, admin) and FastAPI entrypoint"
```

---

### Task 10: Docker + README + 运行验证

**Files:**
- Create: `docker-compose.yml`
- Create: `Dockerfile`
- Create: `README.md`
- Create: `.env.example`

- [ ] **Step 1: 创建 docker-compose.yml**

```yaml
version: "3.8"

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  gateway:
    build: .
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL=redis://redis:6379/0
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - QWEN_API_KEY=${QWEN_API_KEY}
      - GATEWAY_JWT_SECRET=${GATEWAY_JWT_SECRET:-change-me-in-production}
    depends_on:
      - redis
    volumes:
      - gateway_db:/app/data

volumes:
  redis_data:
  gateway_db:
```

- [ ] **Step 2: 创建 Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY config/ ./config/
COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: 创建 .env.example**

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
QWEN_API_KEY=sk-...
GATEWAY_JWT_SECRET=your-secret-key-change-in-production
REDIS_URL=redis://localhost:6379/0
```

- [ ] **Step 4: 创建 README.md**

```markdown
# LLM Gateway

Unified LLM routing gateway with intelligent tier-based routing, load balancing, and unified authentication.

## Features

- **Hybrid Routing**: Rule-based matching + AI intent classification fallback
- **Load Balancing**: Weighted round-robin + least connections across model providers
- **Unified Auth**: API Key + JWT authentication
- **Streaming**: SSE streaming and non-streaming responses
- **Metrics**: Token usage tracking and per-user billing

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 2. Start with Docker Compose
docker compose up -d

# 3. Or run locally
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## API

- `POST /api/runs` — Send chat request (stream/non-stream)
- `POST /api/auth/keys` — Create API key
- `GET /api/models` — List available models
- `GET /api/metrics` — Gateway metrics

See `docs/superpowers/specs/2026-04-09-llm-gateway-design.md` for full spec.

## Config

- `config/gateway.yaml` — Gateway settings (rules, timeouts, auth)
- `config/models.yaml` — Model providers, tiers, weights
```

- [ ] **Step 5: 完整测试**

```bash
cd /root/llm_gateway && pytest tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 6: 启动验证**

```bash
cd /root/llm_gateway
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
sleep 2
curl http://localhost:8000/health
# Expected: {"status":"ok"}
```

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml Dockerfile .env.example README.md
git commit -m "feat: docker setup and documentation"
```

---

