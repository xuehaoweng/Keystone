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

    @classmethod
    def clear(cls):
        cls._adapters.clear()


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
