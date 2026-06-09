import json

import pytest
import pytest_httpx

from app.adapters.anthropic_adapter import AnthropicAdapter
from app.adapters.base import AdapterRegistry, ChatResult, ModelConfig
from app.adapters.kimi_adapter import KimiAdapter
from app.adapters.openai_adapter import OpenAIAdapter
from app.adapters.qwen_adapter import QwenAdapter
from app.config import get_models_config


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
    AdapterRegistry.clear()


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


def test_kimi_uses_current_moonshot_api_host():
    provider_cfg = get_models_config()["providers"]["kimi"]

    assert provider_cfg["base_url"] == "https://api.moonshot.ai/v1"


def test_kimi_code_uses_coding_api_host():
    models_config = get_models_config()
    provider_cfg = models_config["providers"]["kimi_code"]
    model_cfg = next(m for m in models_config["models"] if m["name"] == "kimi-for-coding")

    assert provider_cfg["base_url"] == "https://api.kimi.com/coding/v1"
    assert model_cfg["provider"] == "kimi_code"


@pytest.mark.asyncio
async def test_kimi_adapter_sends_thinking_disabled_by_default(
    httpx_mock: pytest_httpx.HTTPXMock,
    monkeypatch,
):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    httpx_mock.add_response(
        json={
            "id": "chat-123",
            "model": "kimi-k2.5",
            "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )

    adapter = KimiAdapter(ModelConfig(name="kimi-k2.5", provider="kimi", tier="cheap"))
    result = await adapter.chat(messages=[{"role": "user", "content": "Hi"}])

    request = httpx_mock.get_request()
    assert request is not None
    assert str(request.url) == "https://api.moonshot.ai/v1/chat/completions"
    body = json.loads(request.content)
    assert body["thinking"] == {"type": "disabled"}
    assert "temperature" not in body
    assert result.content == "Hello"


@pytest.mark.asyncio
async def test_kimi_code_adapter_uses_fixed_model_id(
    httpx_mock: pytest_httpx.HTTPXMock,
    monkeypatch,
):
    monkeypatch.setenv("KIMI_CODE_API_KEY", "test-key")
    httpx_mock.add_response(
        json={
            "id": "chat-123",
            "model": "kimi-for-coding",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        }
    )

    adapter = KimiAdapter(ModelConfig(name="kimi-for-coding", provider="kimi_code", tier="cheap"))
    result = await adapter.chat(messages=[{"role": "user", "content": "Hi"}])

    request = httpx_mock.get_request()
    assert request is not None
    assert str(request.url) == "https://api.kimi.com/coding/v1/chat/completions"
    body = json.loads(request.content)
    assert body["model"] == "kimi-for-coding"
    assert "thinking" not in body
    assert result.content == "OK"
